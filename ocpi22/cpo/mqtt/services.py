import time

from kombu.exceptions import OperationalError
from pydantic import ValidationError

import logging
from functools import wraps

from django.db import close_old_connections
from django.db.utils import OperationalError as DjangoOperationalError, InterfaceError
from django.core.exceptions import ValidationError as DjangoValidationError

from ocpi22.choices import AuthorizationEnum, OcpiModuleEnum
from ocpi22.cpo.api import process_meter_values
from ocpi22.cpo.mqtt.mqtt_publisher import publish_auth_response
from ocpi22.cpo.mqtt.schemas import (
    MeterValues,
    EvseStatusUpdate,
    TokenAuthorizationMessageIn,
    TokenAuthorizationResponse,
)
from ocpi22.cpo.mqtt.tasks import save_and_send_evse_status_updates
from ocpi22.cpo.session_cache import save_to_session_cache
from ocpi22.cpo.util import find_our_evse
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.routing import find_route_from_credentials
from ocpi22.sessions.util import create_session
from ocpi22.tokens.auth import TokenAuthorization, authorize_token
from ocpiconnector.party import Party

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def ensure_db_connection(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (DjangoOperationalError, InterfaceError) as e:
            error_msg = str(e).lower()

            if any(
                err in error_msg for err in ["server has gone away", "2006", "2013"]
            ):
                logger.warning(
                    f"Database connection lost in {func.__name__}, retrying once: {e}"
                )

                close_old_connections()
                time.sleep(0.1)

                try:
                    return func(*args, **kwargs)
                except Exception as retry_error:
                    logger.error(
                        f"Database retry failed in {func.__name__}: {retry_error}"
                    )
                    raise
            else:
                raise

    return wrapper


def _decode_message(message):
    try:
        return message.payload.decode("utf-8")
    except UnicodeDecodeError:
        logger.exception(f"Failed to decode {message.topic} message")
        return None


@ensure_db_connection
def process_meter_values_data(message) -> None:
    decoded_meter_message = _decode_message(message)
    if not decoded_meter_message:
        return
    try:
        meter_values = MeterValues.model_validate_json(decoded_meter_message)
    except ValidationError as e:
        logger.exception(f"Failed to validate {message.topic} message: {e}")
        return
    try:
        kwargs = meter_values.model_dump()
        session = Session.objects.get(uid=kwargs.pop("session_id"))
        process_meter_values(request=None, session=session, **kwargs)
    except OperationalError:
        logger.exception("Celery operational error")
    except DjangoOperationalError:
        raise
    except Exception:
        logger.exception("An unexpected error occurred")
    return


@ensure_db_connection
def process_status_update_data(message) -> None:
    decoded_message = _decode_message(message)
    if not decoded_message:
        return
    try:
        evse_schema = EvseStatusUpdate.model_validate_json(decoded_message)
    except ValidationError as e:
        logger.warning(
            f"Failed to parse {message.topic} message",
            extra={"payload": decoded_message},
            exc_info=e,
        )
        return

    # Todo: Find the Session which may be active on the EVSE
    #       Store the status update in the database, optimise for querying per Session
    #       Convert the stored status updates to ChargingPeriods in OCPI Session and CDR

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


@ensure_db_connection
def process_authorize_data(message):
    decoded_message = _decode_message(message)
    if not decoded_message:
        return
    try:
        token_auth_message = TokenAuthorizationMessageIn.model_validate_json(  # noqa
            decoded_message
        )
    except ValidationError:
        logger.exception(f"Failed to parse {message.topic} message")
        return
    _authorize_and_publish(token_auth_message, message)
    return


def _publish_not_allowed_auth_response(correlation_id: str):
    not_allowed_message = TokenAuthorizationResponse(
        allowed=AuthorizationEnum.NOT_ALLOWED,
        correlation_id=correlation_id,
        session_id=None,
    )
    publish_auth_response(not_allowed_message)
    return


def _authorize_and_publish(
    token_auth_message: TokenAuthorizationMessageIn, message: str
):
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
            f"Unable to authorize token from MQTT message: EVSE with ID '{token_auth_message.evse_id}' not found",
            extra={"mqtt_message": message},
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
            "MQTT authorization failed miserably for auth message",
            extra={"mqtt_message": message},
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
