import logging
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urljoin

import pytz
import requests
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Prefetch
from django.urls import reverse
from pydantic_core import PydanticSerializationError, ValidationError
from requests import Response

from integrations.hubject.client import HubjectClient
from integrations.hubject.ocpi_to_oicp_converter import (
    convert_to_charging_notification_progress,
    convert_to_charging_notification_start,
    convert_to_charging_notification_end,
)
from integrations.hubject.oicp_to_ocpi_converter import (
    map_successful_oicp_authorization_response_to_ocpi_221,
)
from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    ActionType,
    OperatorEvseData,
    PricingProductData,
    ERoamingPushPricingProductData,
    OperatorID,
    ERoamingAuthorizeStart,
    Identification,
    UID,
    RFIDMifareFamilyIdentificationClass,
    ChargingNotificationType,
    ChargingNotificationBase,
    ERoamingPushEvseStatus,
    OperatorEvseStatus,
    EvseStatusRecordItem,
    EvseID,
    ERoamingAcknowledgment,
    ERoamingAuthorizeRemoteStart,
    StatusCode,
)
from integrations.solid_to_hubject_converter import SolidToHubjectConverter
from integrations.hubject.schemas import HubjectDefaultTariff
from ocpi22.choices import OcpiRolesEnum, TokenType
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Location, Connector, Evse
from ocpi22.models.tariff import SolidTariff
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi
from ocpi22.util import build_absolute_uri
from ocpiconnector.exceptions import ConnectorTariffNotFoundError
from ocpiconnector.ocpi_identities import get_our_identity
from ocpiconnector.party import Party
from util import with_trailing_slash
from typing import Any, TYPE_CHECKING, Optional
from ocpi22.tasks import send_hubject_request

if TYPE_CHECKING:
    from ocpi22.models.session import Session
    from ocpi22.models.cdr import Cdr


logger = logging.getLogger(__name__)


class HubjectService:
    client = HubjectClient()
    converter = SolidToHubjectConverter()

    @staticmethod
    def get_operator_evse_data(party: Party) -> OperatorEvseData | None:
        locations = Location.objects.filter(
            ocpi_master__party_id=party.party_id,
            ocpi_master__country_code=party.country_code,
        )
        evse_data_records = []
        operator_name = None

        if len(locations) == 0:
            return

        locations = Location.objects.prefetch_related(
            Prefetch(
                "evses",
                queryset=Evse.objects.prefetch_related(
                    Prefetch(
                        "connectors",
                        queryset=Connector.objects.prefetch_related("tariff_ids"),
                        to_attr="connectors_with_tariffs",
                    )
                ),
                to_attr="evses_with_connectors",
            )
        )

        for location in locations:
            tmp_operator_evse_data = (
                HubjectService.converter.convert_to_operator_evse_data(location)
            )
            evse_data_records.extend(tmp_operator_evse_data.EvseDataRecord)
            operator_name = tmp_operator_evse_data.OperatorName

            for evse in location.evses_with_connectors:
                for connector in evse.connectors_with_tariffs:
                    if len(connector.get_tariffs()) == 0:
                        raise ConnectorTariffNotFoundError(
                            evse.evse_id,
                            connector.standard,
                            f"No Tariff found for Evse {evse.evse_id} and connector {connector.standard}",
                        )

        if len(evse_data_records) == 0:
            return None

        return OperatorEvseData(
            OperatorID=OperatorID(root=str(party)),
            OperatorName=operator_name,
            EvseDataRecord=evse_data_records,
        )

    def get_evse_full_load_payload(
        self, operator_id: Party
    ) -> ERoamingPushEvseData | None:
        operator_evse_data: OperatorEvseData = self.get_operator_evse_data(operator_id)

        if operator_evse_data is None:
            return

        return ERoamingPushEvseData(
            ActionType=ActionType.fullLoad,
            OperatorEvseData=operator_evse_data,
        )

    @staticmethod
    def post_evse_full_load(operator_id: str, payload: ERoamingPushEvseData) -> dict:
        full_load_url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"evsepush/v23/operators/{operator_id}/data-records",
        )

        try:
            payload_json = payload.model_dump(mode="json")

            response = HubjectService.client.post(full_load_url, json=payload_json)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "errorType": "HTTP Error",
                    "error": f"{response.status_code} : {response.text}",
                }
        except PydanticSerializationError as e:
            logger.exception("Pydantic validation failed")
            return {
                "success": False,
                "errorType": "Pydantic validation failed",
                "error": e.args[0],
            }
        except HTTPError as exc:
            logger.exception("HTTP error occurred")
            return {
                "success": False,
                "errorType": "HTTP request failed",
                "error": exc.args[0],
            }

    @staticmethod
    async def post_authorize_request(
        operator_id: str, token_id: str
    ) -> tuple[Any, dict | None, Any]:
        url = f"{with_trailing_slash(settings.HUBJECT_URL)}charging/v21/operators/{operator_id}/authorize/start"

        try:
            payload = ERoamingAuthorizeStart(
                operator_id=OperatorID(root=operator_id),
                identification=Identification(
                    RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                        UID=UID(root=token_id)
                    )
                ),
            )
            payload_dict = payload.model_dump(exclude_none=True, by_alias=True)
        except ValidationError:
            logger.exception()
            raise
        try:
            response = HubjectService.client.post(
                url, json=payload_dict, headers={"accept": "application/json"}
            )
        except requests.exceptions.RequestException:
            logger.exception("Requests exception during authorization with Hubject")
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "Request error occurred",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                CredentialsRole.objects.none(),
            )

        try:
            response_json = response.json()
            logger.info(
                f"Hubject authorize for token: {token_id} and operator id: {operator_id} responded: {response_json}"
            )
            status_code = response_json.get("StatusCode", {}).get("Code")
            mapped_response = None
            ocpi_master = None
            if response.status_code == 200 and status_code == "000":
                ocpi_master = await sync_to_async(get_credentialsrole)(
                    credentials=None,
                    party=Party.from_str(response_json.get("ProviderID", "*")),
                    create=True,
                    role=OcpiRolesEnum.EMSP,
                )
                mapped_response = (
                    map_successful_oicp_authorization_response_to_ocpi_221(
                        response_json, token_id
                    )
                )

            return (
                response.status_code,
                mapped_response,
                ocpi_master,  # Todo: Rename ocpi_master, since it is used for OICP MSP identification also
            )
        except Exception:
            logger.exception("Exception during authorization with Hubject")
            return (
                404,
                {
                    "allowed": "NOT_ALLOWED",
                    "status_code": Ocpi.ServerError.GENERIC_SERVER_ERROR,
                    "status_message": "",
                    "timestamp": datetime.now(pytz.utc).strftime(
                        settings.OCPI_DATE_FORMAT
                    ),
                },
                CredentialsRole.objects.none(),
            )

    def get_default_tariffs(self):
        if not (
            settings.DEFAULT_OICP_PRICE
            and settings.DEFAULT_OICP_CURRENCY
            and settings.DEFAULT_OICP_PRICE_REFERENCE
        ):
            raise ValueError(
                "Please set DEFAULT_OICP_PRICE, DEFAULT_OICP_CURRENCY, and DEFAULT_OICP_REFERENCE in environment variables"
            )

        default_price = float(settings.DEFAULT_OICP_PRICE)
        default_currency = settings.DEFAULT_OICP_CURRENCY
        default_reference = settings.DEFAULT_OICP_PRICE_REFERENCE

        if default_price < 0:
            raise ValueError("DEFAULT_OICP_PRICE must be positive")

        solid_price_component = HubjectDefaultTariff.get_price_component(
            default_reference
        )
        return HubjectDefaultTariff(
            currency=default_currency,
            price_component=solid_price_component,
            price=default_price,
        )

    def get_all_pricing_products(self, party: Party) -> PricingProductData:
        solid_tariffs = SolidTariff.objects.filter(
            operator__country_code=party.country_code,
            operator__party_id=party.party_id,
        )

        if len(solid_tariffs) == 0:
            raise SolidTariff.DoesNotExist(f"No SolidTariffs found for {str(party)}")

        solid_default_tariff = self.get_default_tariffs()

        operator_name = solid_tariffs[0].operator.business_details.name
        return HubjectService.converter.convert_to_pricing_product_data(
            solid_tariffs,
            solid_default_tariff,
            get_our_identity(OcpiRolesEnum.CPO.value),
            operator_name,
        )

    def get_push_pricing_product_data_payload(
        self, pricing_product_data: PricingProductData, action_type: ActionType
    ) -> ERoamingPushPricingProductData:
        return ERoamingPushPricingProductData(
            ActionType=action_type,
            PricingProductData=pricing_product_data,
        )

    def post_pricing_products_full_load(
        self, operator_id: str, payload: ERoamingPushPricingProductData
    ) -> dict:
        full_load_url = urljoin(
            with_trailing_slash(settings.HUBJECT_URL),
            f"dynamicpricing/v10/operators/{operator_id}/pricing-products",
        )

        try:
            payload_json = payload.model_dump(mode="json")

            response = HubjectService.client.post(full_load_url, json=payload_json)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "errorType": "HTTP Error",
                    "error": f"{response.status_code} : {response.text}",
                }
        except PydanticSerializationError as e:
            logger.exception("Pydantic validation failed")
            return {
                "success": False,
                "errorType": "Pydantic validation failed",
                "error": str(e),
            }

    @classmethod
    def create_charging_notification_payload(
        cls, session, notification_type: ChargingNotificationType
    ) -> ChargingNotificationBase:
        match notification_type:
            case ChargingNotificationType.Start:
                payload = convert_to_charging_notification_start(session)
            case ChargingNotificationType.End:
                payload = convert_to_charging_notification_end(session)
            case ChargingNotificationType.Progress:
                payload = convert_to_charging_notification_progress(session)
            case _:
                raise ValueError(
                    f"Unsupported session notification type: {notification_type}"
                )
        return payload

    @classmethod
    def send_update(
        cls,
        session: "Session",
        notification_type: ChargingNotificationType,
    ) -> None:
        """
        Send an update to the OICP client based on the session and update type.
        """
        payload = cls.create_charging_notification_payload(session, notification_type)
        try:
            cls.post_charging_notification(payload)
            logger.info("Notification sent successfully")
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP error: {e.response.status_code}",
                exc_info=True,
                extra={"hubject_response": e.response.text},
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {e}")
        except Exception as e:
            logger.exception(e)
        return

    @staticmethod
    def post_charging_notification(
        payload,
    ) -> Response:
        url = f"{settings.HUBJECT_URL}notificationmgmt/v11/charging-notifications"
        response = HubjectService.client.post(
            url, json=payload.model_dump(mode="json", by_alias=True)
        )
        response.raise_for_status()
        return response

    @classmethod
    def _get_evse_status_update_payload(
        cls, evse: Evse, operator_id: str, operator_name: str
    ) -> ERoamingPushEvseStatus:
        return ERoamingPushEvseStatus(
            action_type=ActionType.update,
            operator_evse_status=OperatorEvseStatus(
                operator_id=OperatorID(root=operator_id),
                operator_name=operator_name,
                evse_status_record=[
                    EvseStatusRecordItem(
                        evse_id=EvseID(root=evse.evse_id),
                        evse_status=cls.converter.convert_ocpi_evse_status(evse.status),
                    )
                ],
            ),
        )

    @classmethod
    def post_eroaming_push_evse_status(cls, evse: Evse, retries=3) -> None:
        if not evse:
            logger.warning("No EVSE provided for hubject status update")
            return
        ocpi_master = evse.location.ocpi_master
        operator_id = f"{ocpi_master.country_code}*{ocpi_master.party_id}"
        operator_name = ocpi_master.business_details.name

        try:
            payload = cls._get_evse_status_update_payload(
                evse, operator_id, operator_name
            )
        except (ValidationError, ValueError):
            logger.error(
                "Failed to create payload for EVSE status update", exc_info=True
            )
            return

        payload_json = payload.model_dump(mode="json", by_alias=True)

        url = (
            f"{settings.HUBJECT_URL}evsepush/v21/operators/{operator_id}/status-records"
        )

        send_hubject_request.delay(payload_json, url, "post")

    @staticmethod
    def post_eroaming_charge_detail_record(
        operator_id: str, cdr: Optional["Cdr"], session_id=None, retries=3
    ) -> dict:
        from ocpi22.models.cdr import Cdr

        if cdr is None:
            if session_id is None:
                logger.warning(
                    "Neither CDR nor session_id provided for CDR post for Hubject"
                )
                return {
                    "success": False,
                    "errorType": "Invalid Input",
                    "error": "Either CDR or session_id must be provided.",
                }

            cdr = Cdr.objects.filter(session_id=session_id).first()
            if not cdr:
                logger.warning(f"No CDR found for session_id {session_id}")
                return {
                    "success": False,
                    "errorType": "Invalid Input",
                    "error": f"No CDR found for session_id {session_id}.",
                }
            if not cdr.route_through_oicp:
                logger.warning(
                    f"CDR for session_id {session_id} has not routed through OICP"
                )
                return {
                    "success": False,
                    "errorType": "Incompatible CDR",
                    "error": f"CDR with session id {session_id} has not routed through OICP",
                }

        url = f"{settings.HUBJECT_URL}cdrmgmt/v22/operators/{operator_id}/charge-detail-record"

        try:
            payload = (
                HubjectService.converter.convert_cdr_to_eroaming_charging_detail_record(
                    cdr
                )
            )
            payload_json = payload.model_dump(
                mode="json", exclude_none=True, by_alias=True
            )
        except ValidationError as ve:
            logger.error("Failed to create payload for Hubject CDR", exc_info=True)
            return {
                "success": False,
                "errorType": "Validation Error",
                "error": str(ve),
            }

        retry_policy = dict(max_retries=retries, interval_start=5)
        send_hubject_request.apply_async(
            args=(payload_json, url, "post"), retry=True, retry_policy=retry_policy
        )
        logger.info("Hubject CDR post task queued")
        return {
            "success": True,
            "message": "Sent CDR to hubject",
        }

    @staticmethod
    def decode_country_code_and_party_id(
        provider_id: str | None,
    ) -> tuple[str | None, str | None]:
        if provider_id is None:
            return None, None
        if "*" in provider_id:
            return tuple(provider_id.split("*", 1))
        elif "-" in provider_id:
            return tuple(provider_id.split("-", 1))
        elif len(provider_id) == 5 and provider_id.isalnum():
            # Assuming the format is 'CCPPP' where CC is country code and PPP is party ID
            return provider_id[:2], provider_id[2:]
        else:
            raise ValueError(f"Invalid ProviderID format: {provider_id}")

    def _prepare_start_session_data(
        self, remote_start_command, evse: Evse, sender_party: Party
    ) -> dict:
        command_id = remote_start_command.emp_partner_session_id
        contract_id = (
            remote_start_command.identification.RemoteIdentification.EvcoID.root
        )
        if not contract_id:
            raise ValidationError("EvcoID is required for remote start command")
        return {
            "response_url": build_absolute_uri(
                reverse("chargepoint-remote-command-result", args=(command_id,))
            ),
            "token": {
                "uid": contract_id,  # Hubject does not send a token UID for remote start
                "country_code": sender_party.country_code,
                "party_id": sender_party.party_id,
                "type": TokenType.APP_USER.value,
                "contract_id": contract_id,
            },
            "location_id": evse.location.uid,
            "evse_uid": evse.uid,
            "connector_id": evse.connectors.first().uid
            if evse.connectors.exists()
            else "",
            "authorization_reference": remote_start_command.emp_partner_session_id,
        }

    def process_remote_start_command(
        self, remote_start_command: ERoamingAuthorizeRemoteStart
    ):
        from ocpi22.commands.serializers import StartSessionSerializer

        logger.info(
            "Remote start command received from Hubject",
            extra={"command": remote_start_command},
        )

        evse = Evse.objects.filter(evse_id=remote_start_command.evse_id.root).first()

        if not evse:
            logger.error(f"EVSE with ID {remote_start_command.evse_id.root} not found")
            return ERoamingAcknowledgment(
                result=False,
                status_code=StatusCode(Code="603"),
                session_id=remote_start_command.session_id,
                cpo_partner_session_id="",
                emp_partner_session_id=remote_start_command.emp_partner_session_id,
            )

        try:
            sender_country_code, sender_party_id = (
                self.decode_country_code_and_party_id(
                    remote_start_command.provider_id.root
                )
            )
        except ValueError as ve:
            logger.error(f"Failed to decode ProviderID: {ve}")
            return ERoamingAcknowledgment(
                result=False,
                status_code=StatusCode(Code="300"),
                session_id=remote_start_command.session_id,
                cpo_partner_session_id="",
                emp_partner_session_id=remote_start_command.emp_partner_session_id,
            )

        sender_party = Party.from_str(f"{sender_country_code}*{sender_party_id}")

        try:
            data = self._prepare_start_session_data(
                remote_start_command, evse, sender_party
            )
        except ValidationError as ve:
            logger.error(
                f"Validation error preparing start session data for Hubject: {ve}"
            )
            return ERoamingAcknowledgment(
                result=False,
                status_code=StatusCode(Code="022"),
                session_id=remote_start_command.session_id,
                cpo_partner_session_id="",
                emp_partner_session_id=remote_start_command.emp_partner_session_id,
            )

        serializer = StartSessionSerializer(data=data)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            return self._start_session(
                sender_party, remote_start_command, validated_data
            )
        else:
            logger.error(
                "Invalid data for starting remote session for Hubject",
                extra={"errors": serializer.errors, "data": data},
            )
            return ERoamingAcknowledgment(
                result=False,
                status_code=StatusCode(Code="022"),
                session_id=remote_start_command.session_id,
                cpo_partner_session_id="",
                emp_partner_session_id=remote_start_command.emp_partner_session_id,
            )

    def _start_session(
        self,
        sender_party,
        remote_start_command: ERoamingAuthorizeRemoteStart,
        validated_data: dict,
    ) -> ERoamingAcknowledgment:
        from ocpi22.commands.services import StartCommandService
        from ocpi22.commands.repository import SessionRepository

        hubject_party = Party.from_str(settings.HUBJECT_OPERATOR_ID)
        # There is no hub authentication in OCPI 2.x
        credentials_role = get_credentialsrole(
            credentials=None, party=hubject_party, create=True
        )

        service = StartCommandService()
        service.start_session(
            sender_party=sender_party,
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        session = SessionRepository.find_session_by_auth_ref_and_token_uid(
            validated_data
        )
        return ERoamingAcknowledgment(
            result=True,
            status_code=StatusCode(Code="000"),
            session_id=remote_start_command.session_id,
            cpo_partner_session_id=session.uid if session else "",
            emp_partner_session_id=remote_start_command.emp_partner_session_id,
        )
