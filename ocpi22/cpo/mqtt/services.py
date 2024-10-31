from django.db.models import F, Value
from django.db.models.functions import Concat
from pydantic import ValidationError

import logging
from ocpi22.cpo.mqtt.schemas import MeterValues, EvseStatusUpdate
from ocpi22.cpo.mqtt.tasks import process_meter_values, save_and_send_evse_status_updates
from ocpi22.models.location import Evse

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def _decode_message(message):
    try:
        return message.payload.decode()
    except UnicodeDecodeError:
        logger.exception(f"Failed to decode {message.topic} message")
        return None


def process_meter_values_data(message) -> None:
    decoded_meter_message = _decode_message(message)
    if not decoded_meter_message:
        return
    try:
        meter_values = MeterValues.model_validate_json(decoded_meter_message)
    except ValidationError:
        logger.exception(f"Failed to validate {message.topic} message")
        return
    try:
        process_meter_values.apply_async(kwargs=meter_values.model_dump(mode="json"),
                                         expires=35)  # Switch to the below call after setting up celery
    except Exception as e:
        logger.exception(f"Failed to parse message: {e}")
    return


def process_status_update_data(message) -> None:
    logger.info("What's here")
    decoded_evse_message = _decode_message(message)
    if not decoded_evse_message:
        return
    try:
        evse_schema = EvseStatusUpdate.model_validate_json(decoded_evse_message)
    except ValidationError:
        logger.exception(f"Failed to parse {message.topic} message")
        return
    evse_data = EvseStatusUpdate.model_dump(evse_schema, mode="json")
    save_and_send_evse_status_updates.apply_async(kwargs=evse_data,
                                                  expires=35)
    logger.info("And Im done here status")# Switch to the below call after setting up celery
    return
