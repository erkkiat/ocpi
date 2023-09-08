import os
from functools import wraps

from django.conf import settings
from django.utils.safestring import mark_safe
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from ocpi22.messages import messages
from ocpi22.models.location import Location
from ocpi22.ocpi.util import OCPIResponse


def premium_message(request):
    payment_link = os.environ.get('PAYMENT_LINK', 'https://buy.stripe.com/3cs8zZ6HS56048g00b')
    messages.info(request, mark_safe(
        'This is a Premium feature. You can activate all functionality by '
        '<a class="alert-link" target="subscribe" '
        f'href="{payment_link}">subscribing to Premium</a>.'
    ))


def requires_premium(func):
    @wraps(func)
    def check_premium(self, request, *args, **kwargs):
        if not settings.PREMIUM:
            premium_message(request)
            return Response(PREMIUM_MESSAGE, status=status.HTTP_426_UPGRADE_REQUIRED)
        return func(self, request, *args, **kwargs)

    check_premium.__name__ = func.__name__
    return check_premium


class NoPremiumViewSet(ViewSet):
    queryset = Location.objects.none()

    def get_view_name(self):
        return 'This is a Premium Feature'

    def put(self, request):
        premium_message(request)
        return OCPIResponse(PREMIUM_RESPONSE, status=status.HTTP_426_UPGRADE_REQUIRED)

    def post(self, request):
        premium_message(request)
        return OCPIResponse(PREMIUM_RESPONSE, status=status.HTTP_426_UPGRADE_REQUIRED)

    def get(self, request):
        premium_message(request)
        return OCPIResponse(PREMIUM_RESPONSE, status=status.HTTP_426_UPGRADE_REQUIRED)

    def list(self, request):
        premium_message(request)
        return OCPIResponse(PREMIUM_RESPONSE, status=status.HTTP_426_UPGRADE_REQUIRED)


PREMIUM_MESSAGE = 'This feature is available in the Premium subscription. ' \
                  'You can upgrade at http://ocpi.guide/compare/'
PREMIUM_RESPONSE = dict(
    status_message=PREMIUM_MESSAGE,
    status_code=2999
)
