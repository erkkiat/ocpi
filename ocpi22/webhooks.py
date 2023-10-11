from collections import OrderedDict
from typing import Optional

import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError

from ocpi22 import logging as logging
from ocpi22.serializers import CallbacksSerializer
from ocpi22.util import build_callback_request
from ocpiconnector.util import Timer


def send_to_webhook(data: dict = None, serializer=None, serialized_data=None,
                    outbound_serializer=None, timeout=10) -> Optional[dict]:
    if settings.PERFORMANCE_TEST:
        return {}
    assert issubclass(serializer, CallbacksSerializer), \
        'The serializer needs to be inherited from CallbacksSerializer'
    assert not data or isinstance(data, (dict, OrderedDict))
    try:
        if not serialized_data:
            OutboundSerializer = outbound_serializer or serializer.OutboundSerializer
            outbound_serializer = OutboundSerializer(data=data)
            assert outbound_serializer.is_valid(), outbound_serializer.errors
            serialized_data = outbound_serializer.data

        url, kwargs_update = build_callback_request(serializer.URL, serialized_data)
        if url:
            kwargs = {}
            headers = {'content-type': 'application/json', 'accept': 'application/json'}
            kwargs.update(kwargs_update)

            response = requests.put(
                url=url,
                json=serialized_data,
                headers=headers,
                verify=False,
                timeout=timeout,
                **kwargs)
            logging.info(f'Webhook {serializer.URL} at {url} responded in {response.elapsed}')

            if hasattr(serializer, 'ResponseSerializer'):
                response_json = response.json()
                response_serializer = serializer.ResponseSerializer(data=response_json)
                if response_serializer.is_valid():
                    return response_json
                else:
                    logging.error(f'Got a malformed response from webhook at {url}: {response_json}')
                    return None
        else:
            logging.info(f'No webhook {serializer.URL} specified => no action')
    except (IOError, ValueError, ValidationError) as e:
        logging.error(f'Problem communicating with webhook {serializer.__class__}: {e}')
        raise
    except Exception as e:
        logging.error(f'Webhook error: {e}')
        raise

    return None
