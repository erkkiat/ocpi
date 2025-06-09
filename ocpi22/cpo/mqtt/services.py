from kombu.exceptions import OperationalError
from pydantic import ValidationError

import logging
from functools import wraps

from django.db import close_old_connections
from django.db.utils import OperationalError as DjangoOperationalError
from ocpi22.cpo.api import process_meter_values
from ocpi22.cpo.mqtt.schemas import MeterValues, EvseStatusUpdate
from ocpi22.cpo.mqtt.tasks import save_and_send_evse_status_updates
from ocpi22.models.session import Session

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def ensure_db_connection(func):
    """Decorator to handle database connection errors in MQTT message processing"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DjangoOperationalError as e:
            if "server has gone away" in str(e).lower() or "2006" in str(e):
                logger.warning("Database connection lost, reconnecting...")
                close_old_connections()
                return func(*args, **kwargs)
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
    decoded_evse_message = _decode_message(message)
    if not decoded_evse_message:
        return
    try:
        evse_schema = EvseStatusUpdate.model_validate_json(decoded_evse_message)
    except ValidationError:
        logger.exception(f"Failed to parse {message.topic} message")
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
