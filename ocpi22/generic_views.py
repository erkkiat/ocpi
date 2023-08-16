import ocpi22.logging as logging

import redis
from django.conf import settings
from django.utils.translation import gettext as _
from rest_framework import viewsets, status
from rest_framework.response import Response

from ocpi22.util import MyMetadata, get_callbacks_parameter


class WebhookViewSet(viewsets.GenericViewSet):
    metadata = MyMetadata()
    outbound_data_serializer = None
    response_data_serializer = None
    serializer = None

    def get_extra_metadata(self, _request) -> dict:
        outbound_serializer = self.outbound_data_serializer or self.serializer.OutboundSerializer
        response_serializer = self.response_data_serializer
        if hasattr(self.serializer, 'ResponseSerializer'):
            response_serializer = self.serializer.ResponseSerializer

        return dict(
            webhook_details=dict(
                data_sent=self.metadata.get_serializer_info(outbound_serializer()),
                expected_response=self.metadata.get_serializer_info(response_serializer()) \
                    if response_serializer else _('Response can be anything')
            )
        )

    def _get_callbacks(self):
        data = dict(
            [(key, get_callbacks_parameter(key)) for key in self.serializer.fields.keys()]
        )
        serializer = self.serializer_class(instance=data)
        return serializer.data

    def webhook(self, request):
        if settings.PERFORMANCE_TEST:
            return Response(dict(status_text='OK'), status=status.HTTP_200_OK)
        try:
            if request.method == 'GET':
                result = self._get_callbacks()
                return Response(result)
            if request.method in {'POST', 'PATCH'}:
                partial = bool(request.method == 'PATCH')
                serializer = self.serializer_class(data=request.data, partial=partial)
                if serializer.is_valid():
                    serializer.save()
                    return Response(self._get_callbacks())
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except redis.exceptions.ConnectionError as e:
            logging.error(f'{settings.HOSTNAME}: Cannot read and store callback settings  '
                          f'due to trouble connecting with Redis: {e}')
            return Response(
                dict(
                    status_text='Unable to store settings due to connection problem with Redis. '
                                'This is our fault, sorry. Support has been alerted.'
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(f'{request.method} is not supported', status=status.HTTP_400_BAD_REQUEST)
