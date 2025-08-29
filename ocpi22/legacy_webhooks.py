from collections import OrderedDict
from logging import getLogger
from typing import Optional, Union

import requests
from django.conf import settings
from django.core.exceptions import ValidationError

from ocpi22.models.location import Location, Evse
from ocpi22.serializers.util import CallbacksSerializer
from ocpi22.util import build_callback_request

logger = getLogger(__name__)


def send_to_webhook(
    data: Union[dict, Location, Evse] = None,
    serializer=None,
    serialized_data=None,
    outbound_serializer=None,
    timeout=10,
    ocpi_master=None,
) -> Optional[dict]:
    """
    Webhook function - temporarily disabled.
    Only remote command webhooks are handled by the new webhook system.
    """
    if settings.PERFORMANCE_TEST:
        return {}

    serializer_name = serializer.__class__.__name__ if serializer else "Unknown"
    logger.info(f"Webhook disabled for serializer: {serializer_name}")
    return {}


def send_to_webhook_legacy_for_reference_only(
    data: Union[dict, Location, Evse] = None,
    serializer=None,
    serialized_data=None,
    outbound_serializer=None,
    timeout=10,
    ocpi_master=None,
) -> Optional[dict]:
    if settings.PERFORMANCE_TEST:
        return {}
    if isinstance(data, Location):
        ocpi_master = ocpi_master or data.ocpi_master
        # Send updates for all EVSEs at this Location
        list(
            map(
                lambda evse: send_to_webhook(
                    evse,
                    serializer,
                    serialized_data,
                    outbound_serializer,
                    timeout,
                    ocpi_master,
                ),
                data.evses.all(),
            )
        )  # "list" triggers the evaluation of the map
        return {}
    if isinstance(data, Evse):
        ocpi_master = ocpi_master or data.location.ocpi_master
        return send_to_webhook(
            dict(location_id=data.location.uid, evse_id=data.uid, status=data.status),
            serializer,
            serialized_data,
            outbound_serializer,
            timeout,
            ocpi_master,
        )
    assert issubclass(
        serializer, CallbacksSerializer
    ), "The serializer needs to be inherited from CallbacksSerializer"
    assert not data or isinstance(data, (dict, OrderedDict))
    try:
        if not serialized_data:
            OutboundSerializer = outbound_serializer or serializer.OutboundSerializer
            outbound_serializer = OutboundSerializer(
                data=data, context={"request": None, "ocpi_master": ocpi_master}
            )
            assert outbound_serializer.is_valid(), outbound_serializer.errors
            serialized_data = outbound_serializer.data

        url, kwargs_update = build_callback_request(serializer.URL, serialized_data)
        if url:
            kwargs = {}
            headers = {"content-type": "application/json", "accept": "application/json"}
            kwargs.update(kwargs_update)

            response = requests.post(
                url=url,
                json=serialized_data,
                headers=headers,
                verify=False,
                timeout=timeout,
                **kwargs,
            )
            logger.info(
                f"Webhook {serializer.URL} at {url} responded in {response.elapsed}"
            )

            if getattr(serializer, "ResponseSerializer", None):
                response_json = response.json()
                response_serializer = serializer.ResponseSerializer(data=response_json)
                if response_serializer.is_valid():
                    return response_json
                else:
                    logger.error(
                        f"Got a malformed response from webhook at {url}: {response_json}"
                    )
                    return None
        else:
            logger.info(f"No webhook {serializer.URL} specified")
    except (IOError, ValidationError):
        logger.exception(f"Problem communicating with webhook {serializer.__class__}")
        raise
    except Exception:
        logger.exception("Webhook error")
        raise

    return None
