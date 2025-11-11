from logging import getLogger

from kombu.exceptions import OperationalError
from pydantic import ValidationError

from django.core.exceptions import ValidationError as DjangoValidationError

from ocpi22.choices import AuthorizationEnum, OcpiModuleEnum
from ocpi22.cpo.mqtt.mqtt_publisher import publish_auth_response
from ocpi22.cpo.mqtt.schemas import (
    MeterValues,
    EvseStatusUpdate,
    TokenAuthorizationMessageIn,
    TokenAuthorizationResponse,
)
from ocpi22.cpo.mqtt.tasks import (
    save_and_send_evse_status_updates,
    update_meter_values_async,
)
from ocpi22.cpo.session_cache import save_to_session_cache
from ocpi22.cpo.util import find_our_evse
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.routing import find_route_from_credentials
from ocpi22.sessions.util import create_session
from ocpi22.tokens.auth import (
    TokenAuthorization,
    authorize_token,
)
from ocpiconnector.party import Party

logger = getLogger(__name__)


def _decode_message(message):
    try:
        return message.payload.decode("utf-8")
    except UnicodeDecodeError:
        logger.exception(f"Failed to decode message from topic {message.topic}")
        return None


def process_meter_values_data(message) -> None:
    decoded_meter_message = _decode_message(message)
    if not decoded_meter_message:
        return

    try:
        meter_values = MeterValues.model_validate_json(decoded_meter_message)
    except ValidationError:
        logger.exception(f"Failed to parse message from topic {message.topic}")
        return

    if not meter_values.session_id:
        logger.warning("Meter values message missing session_id")
        return

    meter_data = {
        "session_id": meter_values.session_id,
        "timestamp": meter_values.timestamp.isoformat(),
        "kwh": meter_values.kwh,
        "soc": meter_values.soc,
        "power": meter_values.power,
    }

    try:
        update_meter_values_async.apply_async(kwargs=meter_data, expires=60)
        logger.info(
            f"Dispatched meter values update task for session {meter_values.session_id}"
        )
    except OperationalError:
        logger.exception("Celery operational error while dispatching meter values task")
    except Exception:
        logger.exception("Unexpected error dispatching meter values task")

    return


def process_status_update_data(message) -> None:
    decoded_message = _decode_message(message)
    if not decoded_message:
        return
    try:
        evse_schema = EvseStatusUpdate.model_validate_json(decoded_message)
    except ValidationError as e:
        logger.exception(
            f"Failed to parse message from topic {message.topic}",
            exc_info=e,
        )
        return

    evse_data = evse_schema.model_dump(mode="json")
    try:
        save_and_send_evse_status_updates.apply_async(kwargs=evse_data, expires=35)
    except OperationalError:
        logger.exception("Celery operational error")
    except Exception:
        logger.exception("An unexpected error occurred")
    return


def _find_token_by_uid(token_id):
    return Token.objects.filter(uid__iexact=token_id).first()


def process_authorize_data(message):
    decoded_message = _decode_message(message)
    if not decoded_message:
        return
    try:
        token_auth_message = TokenAuthorizationMessageIn.model_validate_json(
            decoded_message
        )
    except ValidationError:
        logger.exception(f"Failed to parse message from topic {message.topic}")
        return

    _authorize_and_publish(token_auth_message, message.topic)
    return


def _publish_not_allowed_auth_response(correlation_id: str):
    not_allowed_message = TokenAuthorizationResponse(
        allowed=AuthorizationEnum.NOT_ALLOWED,
        correlation_id=correlation_id,
        session_id=None,
    )
    publish_auth_response(not_allowed_message)
    return


def _authorize_and_publish(token_auth_message: TokenAuthorizationMessageIn, topic: str):
    """
    MEMORY OPTIMIZATION:
    - Accept topic string instead of full message object
    """
    try:
        evse = find_our_evse(token_auth_message.evse_id)
    except DjangoValidationError as e:
        logger.warning(
            f"Cannot authorize non existent evse {token_auth_message.evse_id}",
            exc_info=e,
        )
        return
    if not evse:
        logger.error(
            f"Unable to authorize token from MQTT on topic {topic}: "
            f"EVSE with ID '{token_auth_message.evse_id}' not found"
        )
        _publish_not_allowed_auth_response(token_auth_message.correlation_id)
        return

    token: str | Token = (
        _find_token_by_uid(token_auth_message.token_id) or token_auth_message.token_id
    )
    try:
        authorization: TokenAuthorization = authorize_token(
            token, evse.location, evse_id=evse.evse_id
        )
        if not authorization or authorization.allowed != AuthorizationEnum.ALLOWED:
            logger.warning(
                f"Authorization was not allowed by any msps for provided token: {token_auth_message.token_id}"
            )
            _publish_not_allowed_auth_response(token_auth_message.correlation_id)
            return
        session = create_and_save_session(authorization, evse)
        allowed_message = TokenAuthorizationResponse(
            allowed=AuthorizationEnum(authorization.allowed),
            correlation_id=token_auth_message.correlation_id,
            session_id=session.uid,
        )
        publish_auth_response(allowed_message)
    except Exception:
        logger.exception(
            f"MQTT authorization failed on topic {topic}",
        )
        _publish_not_allowed_auth_response(token_auth_message.correlation_id)
        return
    return


def create_and_save_session(authorization: TokenAuthorization, evse: Evse) -> Session:
    token_dict = authorization.token
    ad_hoc_token = AdhocToken(
        uid=token_dict.get("uid"),
        valid=token_dict.get("valid"),
        billed_to=authorization.get_token_party(),
        type=token_dict.get("type"),
        ocpi_master=authorization.msp,
        contract_id=authorization.token.get("contract_id", "-"),
    )
    session = create_session(
        credentials=get_credentialsrole(
            party=Party.from_str(authorization.responding_party)
        ).credentials,
        authorization_reference=authorization.authorization_reference,
        authorization_method=authorization.auth_method,
        billed_to=authorization.get_token_party(),
        ad_hoc_token=ad_hoc_token,
        evse_uid=evse.uid,
        connector_id=None,
        location_id=evse.location.uid,
        hub_session_id=authorization.hub_session_id,
    )
    save_to_session_cache(
        route=find_route_from_credentials(
            credentials=session.credentials, ocpi_module=OcpiModuleEnum.SESSIONS
        ),
        session=session,
    )
    return session
