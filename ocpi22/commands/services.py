from logging import getLogger
from typing import Dict, Any, NamedTuple
import requests
from celery import shared_task
from requests.exceptions import RequestException, Timeout, ConnectionError

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status

from ocpi22.commands.repository import (
    SessionRepository,
    CallBackRepository,
    LocationRepository,
)
from ocpi22.commands.serializers import (
    CommandResponse,
    CommandResultSerializer,
    CommandResultType,
    CommandResponseType,
)
from ocpi22.commands.models import CallBacks, CallBackExecutionStatus
from ocpi22.exceptions import (
    EvseNotFoundError,
    LocationNotFoundError,
    EvseOccupiedError,
    ConnectorNotFoundError,
)
from ocpi22.models.location import Evse, Location, Connector
from ocpi22.models.session import Session
from ocpi22.models.credentials import Credentials
from ocpi22.ocpi.util import OCPIResponse, Ocpi
from ocpi22.ocpi.util_party import get_sender_party
from ocpi22.choices import MessageTexts, OcpiRolesEnum
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.headers import make_headers
from ocpi22.tasks import get_certificate_loaded_request

from webhooks.choices import RemoteCommandType
from webhooks.repository import WebhookRepository

from webhooks.services import WebhookEventService, WebhookExecutionService
from webhooks.models import WebhookEventType
from rest_framework.reverse import reverse
from ocpi22.util import build_absolute_uri, generate_random_token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.sessions.util import create_session
from ocpi22.models import enum

from ocpiconnector.party import Party
from ocpiconnector.ocpi_identities import get_our_party

logger = getLogger(__name__)


class CallbackResult(NamedTuple):
    success: bool
    status_code: int = None
    response_body: str = None
    error_message: str = None


class CallBackService:
    REQUEST_TIMEOUT = 30

    @staticmethod
    def mark_success(
        callback: CallBacks, response_status_code=None, response_body=None
    ):
        callback.execution_status = CallBackExecutionStatus.SUCCESS
        callback.executed_at = timezone.now()
        callback.response_status_code = response_status_code
        callback.response_body = response_body
        callback.save(
            update_fields=[
                "execution_status",
                "executed_at",
                "response_status_code",
                "response_body",
                "updated_at",
            ]
        )

    @staticmethod
    def mark_failed(callback: CallBacks, response_status_code=None, response_body=None):
        callback.execution_status = CallBackExecutionStatus.FAILED
        callback.executed_at = timezone.now()
        callback.response_status_code = response_status_code
        callback.response_body = response_body
        callback.save(
            update_fields=[
                "execution_status",
                "executed_at",
                "response_status_code",
                "response_body",
                "updated_at",
            ]
        )

    @staticmethod
    def create_callback(session, callback_url, authorization_reference):
        return CallBacks.objects.create(
            session=session,
            callback_url=callback_url,
            authorization_reference=authorization_reference,
            execution_status=CallBackExecutionStatus.PENDING,
        )

    @classmethod
    def _get_localized_messages(cls, command_result: CommandResultType, message=None):
        if command_result == CommandResultType.ACCEPTED:
            return []
        elif command_result == CommandResultType.REJECTED:
            if message:
                return [{"language": "en", "text": message}]
            else:
                return MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT", [])
        else:
            messages = MessageTexts.get(command_result.value.upper(), None)
            if not messages:
                return MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT", [])
            else:
                return messages

    @classmethod
    def create_command_result_payload(
        cls, command_result: CommandResultType, message=None
    ):
        data = {
            "result": command_result.value.upper(),
        }
        messages = cls._get_localized_messages(command_result, message)
        data["message"] = messages

        serializer = CommandResultSerializer(data=data)
        if serializer.is_valid():
            return serializer.validated_data
        else:
            logger.error(
                f"CommandResult serializer validation failed: {serializer.errors}"
            )
            return data

    @classmethod
    def execute_callback_request(
        cls,
        callback_url: str,
        payload: dict,
        auth_token: str,
        request: requests.Session,
        to_party: Party = None,
        sender_party: Party = None,
    ) -> CallbackResult:
        if not callback_url:
            logger.error("Cannot execute callback: empty callback_url")
            return CallbackResult(success=False, error_message="Empty callback URL")

        if not auth_token:
            logger.error("Cannot execute callback: empty auth_token")
            return CallbackResult(success=False, error_message="Empty auth token")

        try:
            headers = make_headers(
                token_base64=auth_token, to=to_party, sender=sender_party
            )

            logger.info(f"Sending callback to {callback_url}")

            response = request.post(
                callback_url, json=payload, headers=headers, timeout=cls.REQUEST_TIMEOUT
            )

            response_body = response.text if response.text else None

            if response.status_code < 300:
                logger.info(
                    f"Callback succeeded: {callback_url} - Status {response.status_code}"
                )
                return CallbackResult(
                    success=True,
                    status_code=response.status_code,
                    response_body=response_body,
                )
            else:
                logger.error(
                    f"Callback failed with HTTP {response.status_code}: {callback_url}"
                )
                return CallbackResult(
                    success=False,
                    status_code=response.status_code,
                    response_body=response_body,
                    error_message=f"HTTP {response.status_code}",
                )

        except Timeout:
            error_msg = f"Request timeout after {cls.REQUEST_TIMEOUT} seconds"
            logger.error(f"Callback timeout: {callback_url}", exc_info=True)
            return CallbackResult(success=False, error_message=error_msg)

        except ConnectionError:
            error_msg = "Connection error"
            logger.error(f"Callback connection error: {callback_url}", exc_info=True)
            return CallbackResult(success=False, error_message=error_msg)

        except RequestException:
            error_msg = "Request error"
            logger.error(f"Callback request error: {callback_url}", exc_info=True)
            return CallbackResult(success=False, error_message=error_msg)

        except Exception:
            error_msg = "Unexpected error"
            logger.error(
                f"Unexpected error executing callback: {callback_url}", exc_info=True
            )
            return CallbackResult(success=False, error_message=error_msg)

    @classmethod
    def execute_callback(
        cls, callback: CallBacks, command_result: CommandResultType, message: str = None
    ) -> bool:
        try:
            payload = cls.create_command_result_payload(command_result, message)

            if not callback.session:
                logger.error(f"Callback {callback.id} missing session")
                cls.mark_failed(callback, None, "Missing session")
                return False

            if not callback.session.credentials:
                logger.error(
                    f"Callback {callback.id} session {callback.session.uid} missing credentials"
                )
                cls.mark_failed(callback, None, "Missing credentials")
                return False

            if not callback.session.credentials.theirs:
                logger.error(
                    f"Callback {callback.id} credentials missing 'theirs' token"
                )
                cls.mark_failed(callback, None, "Missing credentials token")
                return False

            auth_token = callback.session.credentials.theirs_base64()

            try:
                sender_party = get_our_party(OcpiRolesEnum.CPO)
            except Exception as e:
                logger.error(
                    f"Failed to get our party info for callback {callback.id}",
                    exc_info=True,
                )
                cls.mark_failed(callback, None, f"Failed to get sender party: {str(e)}")
                return False

            try:
                to_party = callback.session.credentials.get_party()
            except Exception as e:
                logger.error(
                    f"Failed to get eMSP party info for callback {callback.id} session {callback.session.uid}",
                    exc_info=True,
                )
                cls.mark_failed(
                    callback, None, f"Failed to get recipient party: {str(e)}"
                )
                return False

            logger.info(
                f"Executing callback {callback.id} for session {callback.session.uid} - "
                f"From: {sender_party} To: {to_party} Result: {command_result}"
            )

            request = get_certificate_loaded_request(callback.session.credentials.id)

            result = cls.execute_callback_request(
                callback_url=callback.callback_url,
                payload=payload,
                auth_token=auth_token,
                request=request,
                to_party=to_party,
                sender_party=sender_party,
            )

            if result.success:
                logger.info(f"Callback {callback.id} executed successfully")
                cls.mark_success(
                    callback,
                    response_status_code=result.status_code,
                    response_body=result.response_body,
                )
                return True
            else:
                logger.error(f"Callback {callback.id} failed: {result.error_message}")
                cls.mark_failed(
                    callback,
                    response_status_code=result.status_code,
                    response_body=result.error_message,
                )
                return False

        except Exception as e:
            logger.error(
                f"Unexpected error executing callback {callback.id}", exc_info=True
            )
            cls.mark_failed(callback, None, f"Unexpected error: {str(e)}")
            return False


@shared_task(name="ocpi22.commands.send_callback")
def send_callback(
    session_uid: str,
    result: str,
    message: str = None,
) -> None:
    callback = CallBackRepository.find_by_session_uid(session_uid=session_uid)
    if not callback:
        logger.warning(f"No callback found for COMMAND session {session_uid}")
        return
    if callback.execution_status != CallBackExecutionStatus.PENDING:
        logger.info(
            f"Callback for COMMAND session {session_uid} already executed with status {callback.execution_status}, cannot retry"
        )
        return
    result = CommandResultType(result)
    CallBackService.execute_callback(callback, result, message)
    logger.info(
        f"Callback executed for COMMAND session {session_uid} to {callback.callback_url}"
    )
    return


class InvalidSenderPartyError(Exception):
    pass


class RemoteCommandServices:
    def get_validated_sender_party(self, request_meta: Dict[str, Any]) -> Party | None:
        sender_party = get_sender_party(request_meta)

        if not isinstance(sender_party, Party) and len(str(sender_party)) != 6:
            raise InvalidSenderPartyError(
                f"Sender party must be a Party object, got: {type(sender_party)}"
            )
        return sender_party

    def create_ocpi_response(self, result: str, message: str | None = None):
        timeout = 60

        if result == CommandResponseType.REJECTED and message:
            messages = [{"language": "en", "text": message}]
        else:
            default_messages = MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT", [])
            messages = MessageTexts.get(result, default_messages)

        if result == CommandResponseType.ACCEPTED:
            ocpi_status = Ocpi.OK
            http_status = status.HTTP_200_OK
        else:
            ocpi_status = 2000
            http_status = status.HTTP_200_OK

        response_serializer = CommandResponse(
            data={"result": result, "timeout": timeout, "message": messages}
        )

        if not response_serializer.is_valid():
            logger.error(f"Response serializer error: {response_serializer.errors}")
            return OCPIResponse(
                None,
                status_message="Internal error",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return OCPIResponse(
            response_serializer.data, status_code=ocpi_status, http_status=http_status
        )

    def send_webhook_and_save_event(self, webhook, payload, command_type):
        event_type_mapping = {
            RemoteCommandType.START_SESSION: WebhookEventType.REMOTE_START_REQUESTED,
            RemoteCommandType.STOP_SESSION: WebhookEventType.REMOTE_STOP_REQUESTED,
        }

        event_type = event_type_mapping.get(
            command_type,
            f"remote_command.{str(command_type).lower()}_requested",
        )

        event = WebhookEventService.create_event(
            webhook=webhook, event_type=event_type, payload=payload
        )
        response_json = WebhookExecutionService().execute_webhook_event(event)
        return response_json

    def get_valid_webhook(self, command_type: RemoteCommandType):
        webhook = WebhookRepository().get_remote_command_webhook(command_type)
        if not webhook:
            raise ValidationError(f"No webhook configured for {command_type}")
        elif not webhook.active:
            raise ValidationError(f"Inactive webhook found for {command_type}")
        return webhook


class StartCommandService(RemoteCommandServices):
    def __init__(self):
        super().__init__()
        self.webhook_repo = WebhookRepository()
        self.session_repo = SessionRepository()

    def _get_evse(
        self,
        evse_uid: str,
    ) -> Evse:
        evse = Evse.objects.filter(uid=evse_uid).first()
        if not evse:
            raise EvseNotFoundError(f"EVSE not found for evse_uid {evse_uid}")
        return evse

    def _get_location(self, location_uid: str) -> Location:
        location = LocationRepository.find_location_by_uid(location_uid)
        if not location:
            raise LocationNotFoundError(
                f"Location not found for location_id {location_uid}"
            )
        return location

    def _validate_evse_availability(self, evse: Evse):
        if evse.status not in [Evse.AVAILABLE, Evse.CHARGING]:
            raise EvseOccupiedError("Evse is not available for starting a session.")

    def _get_connector(self, connector_uid: str) -> Connector:
        connector = Connector.objects.filter(uid=connector_uid).first()
        if not connector:
            raise ConnectorNotFoundError(
                f"Connector not found for connector_id {connector_uid}"
            )
        return connector

    def _get_first_connector_if_missing(
        self,
        evse: Evse,
        connector_id: str | None = None,
    ) -> Connector:
        if connector_id:
            return self._get_connector(connector_id)
        first_connector = evse.connectors.first()
        if not first_connector:
            raise ConnectorNotFoundError(f"No connector found for evse_uid {evse.uid}")
        logger.info(
            f"Picked connector_id {first_connector.uid} for evse_uid {evse.uid}"
        )
        return first_connector

    def start_session(
        self,
        sender_party: Party,
        credentials: Credentials,
        validated_data: Dict[str, Any],
        hub_session_id: str = None,
    ) -> OCPIResponse:
        session = self.session_repo.find_session_by_auth_ref_and_token_uid(
            auth_reference=validated_data["authorization_reference"],
            token_uid=validated_data["token"]["uid"],
        )

        if not session:
            location = self._get_location(location_uid=validated_data["location_id"])
            evse = self._get_evse(evse_uid=validated_data["evse_uid"])
            self._validate_evse_availability(evse)
            connector = self._get_first_connector_if_missing(
                evse, connector_id=validated_data.get("connector_id")
            )
            billed_to = get_credentialsrole(party=sender_party, create=True)
            ad_hoc_token = AdhocToken(
                billed_to=billed_to.get_party(),
                ocpi_master=billed_to,
                **validated_data["token"],
            )

            with transaction.atomic():
                session = create_session(
                    location_id=location,
                    evse_uid=evse,
                    connector_id=connector.uid,
                    billed_to=billed_to.get_party(),
                    credentials=credentials,
                    authorization_reference=validated_data["authorization_reference"],
                    authorization_method=enum.AuthMethodChoices.COMMAND,
                    ad_hoc_token=ad_hoc_token,
                    hub_session_id=hub_session_id,
                )
                if not session.route_through_oicp:
                    CallBackService.create_callback(
                        session=session,
                        authorization_reference=session.authorization_reference,
                        callback_url=validated_data["response_url"],
                    )
            webhook_response = self.send_start_command_webhook(
                validated_data=validated_data,
                command_type=RemoteCommandType.START_SESSION,
                session=session,
            )
            result_str = (
                webhook_response.get("data", {}).get("result", "REJECTED").upper()
            )
            try:
                result = CommandResponseType(result_str)
            except ValueError:
                logger.warning(
                    f"Invalid result type: {result_str}, defaulting to REJECTED"
                )
                result = CommandResponseType.REJECTED

            return self.create_ocpi_response(result, message=None)

        if session.status == Session.ACTIVE:
            logger.info(
                f"Found existing active session for remote start for token_uid: {validated_data['token']['uid']}, auth_reference: {validated_data['authorization_reference']}"
            )
            return OCPIResponse(
                None,
                status_message="Cannot start - ACTIVE session",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        if session.status in [Session.PENDING, Session.RESERVATION]:
            logger.info(
                f"Retrying existing {session.status} session for remote start with token_uid: {validated_data['token']['uid']} and auth_reference: {validated_data['authorization_reference']}"
            )
            webhook_response = self.send_start_command_webhook(
                validated_data=validated_data,
                command_type=RemoteCommandType.START_SESSION,
                session=session,
            )
            result_str = (
                webhook_response.get("data", {}).get("result", "REJECTED").upper()
            )
            try:
                result = CommandResponseType(result_str)
            except ValueError:
                logger.warning(
                    f"Invalid result type: {result_str}, defaulting to REJECTED"
                )
                result = CommandResponseType.REJECTED

            return self.create_ocpi_response(result, message=None)
        return OCPIResponse(
            None,
            status_message="Cannot start - COMPLETED/INVALID session",
            http_status=status.HTTP_400_BAD_REQUEST,
        )

    @staticmethod
    def _prepare_start_session_payload(
        validated_data: Dict[str, Any],
        session: Session,
    ) -> Dict[str, Any]:
        validated_data["authorization_reference"] = (
            validated_data.get("authorization_reference") or generate_random_token()
        )
        validated_data["token"]["type"] = str(validated_data["token"]["type"])
        payload = {
            "response_url": build_absolute_uri(
                reverse(
                    "chargepoint-remote-command-result",
                    args=(validated_data["authorization_reference"],),
                )
            ),
            "token": validated_data["token"],
            "authorization_reference": validated_data["authorization_reference"],
            "evse_uid": validated_data.get("evse_uid"),
            "connector_id": validated_data.get("connector_id"),
        }
        payload["session_id"] = session.uid

        return payload

    def send_start_command_webhook(
        self,
        validated_data: Dict[str, Any],
        command_type: RemoteCommandType,
        session: Session,
    ) -> Dict[str, Any]:
        webhook = self.get_valid_webhook(command_type=command_type)
        payload = self._prepare_start_session_payload(
            session=session,
            validated_data=validated_data,
        )
        response = self.send_webhook_and_save_event(webhook, payload, command_type)
        return response


class StopCommandServices(RemoteCommandServices):
    def __init__(self):
        super().__init__()
        self.session_repo = SessionRepository()
        self.webhook_repo = WebhookRepository()

    def send_stop_command_webhook(self, payload: dict, command_type: RemoteCommandType):
        webhook = self.get_valid_webhook(command_type=command_type)
        response = self.send_webhook_and_save_event(webhook, payload, command_type)
        return response

    def stop_session(
        self,
        validated_data: Dict[str, Any],
    ) -> OCPIResponse:
        session = self.session_repo.find_session_by_uid(validated_data["session_id"])
        if not session:
            logger.warning(
                f"Could not find any session for provided uid: {validated_data['session_id']}"
            )
            return self.create_ocpi_response(
                CommandResponseType.UNKNOWN_SESSION, "Could not find the session"
            )

        CallBackService.create_callback(
            session=session,
            callback_url=validated_data["response_url"],
            authorization_reference=session.authorization_reference,
        )
        response = self.send_stop_command_webhook(
            payload=validated_data, command_type=RemoteCommandType.STOP_SESSION
        )
        result_str = response.get("data", {}).get("result", "REJECTED").upper()
        try:
            result = CommandResponseType(result_str)
        except ValueError:
            logger.warning(f"Invalid result type: {result_str}, defaulting to REJECTED")
            result = CommandResponseType.REJECTED

        if result == CommandResponseType.ACCEPTED:
            send_callback.delay(
                session_uid=session.uid,
                result=CommandResultType.ACCEPTED.value,
                message=None,
            )
        return self.create_ocpi_response(result)


def process_remote_command(
    request,
    command_serializer,
    webhook_serializer,
    command_prefix,
    extra_actions=None,
):
    logger.warning(
        "process_remote_command is deprecated - use StartSessionService, StopSessionService, etc."
    )

    return OCPIResponse(
        None,
        status_message="This function is deprecated - please use the new service classes",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
