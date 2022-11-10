from collections import OrderedDict

import requests
from rest_framework.exceptions import ValidationError

from ocpi22 import logging as logging
from ocpi22.serializers import CallbacksSerializer
from ocpi22.util import build_callback_request


def send_to_webhook(data: dict, serializer, serialized_data=None, outbound_serializer=None, timeout=5) -> dict:
    assert issubclass(serializer, CallbacksSerializer), \
        'The serializer needs to be inherited from CallbacksSerializer'
    assert isinstance(data, (dict, OrderedDict))
    try:
        if not serialized_data:
            OutboundSerializer = outbound_serializer or serializer.OutboundSerializer
            outbound_serializer = OutboundSerializer(data=data)
            assert outbound_serializer.is_valid(), outbound_serializer.errors
            serialized_data = outbound_serializer.data

        url, kwargs_update = build_callback_request(serializer.URL, serialized_data)

        if url:
            kwargs = {}
            headers = {'content-type': 'application/json'}
            kwargs.update(kwargs_update)

            logging.info(f'Calling webhook at url {url}')

            response = requests.post(
                url=url,
                json=serialized_data,
                headers=headers,
                verify=False,
                timeout=timeout,
                **kwargs)
            if hasattr(serializer, 'ResponseSerializer'):
                data = response.json()
                response_serializer = serializer.ResponseSerializer(data=data)
                if response_serializer.is_valid():
                    return data
                else:
                    logging.error(f'Got a malformed response from webhook at {url}: {data}')
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError, ValidationError) as e:
        logging.error(f'Problem communicating with webhook {serializer.__class__}: {e}')
    return {}
