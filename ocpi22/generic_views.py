import logging

import redis
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.response import Response

from ocpi22.util import MyMetadata, get_callbacks_parameter


class WebhookViewSet(viewsets.GenericViewSet):
    metadata = MyMetadata()

    def _get_callbacks(self):
        data = dict(
            [(key, get_callbacks_parameter(key)) for key in self.serializer.fields.keys()]
        )
        serializer = self.serializer_class(instance=data)
        return serializer.data

    def webhook(self, request):
        try:
            if request.method == 'GET':
                result = self._get_callbacks()
                return Response(result)
            if request.method in ('POST', 'PATCH'):
                partial = bool(request.method == 'PATCH')
                serializer = self.serializer_class(data=request.data, partial=partial)
                if serializer.is_valid():
                    serializer.save()
                    get_callbacks_parameter.cache_clear()
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
