import markdown
from django.utils.html import format_html

from rest_framework import generics
from django.utils.translation import gettext as _

from ocpi22.msp.serializers import (
    MSPAuthorizeCallbackSerializer,
    MSPSessionCallbackSerializer,
    MSPChargePointStatusCallbackSerializer,
)
from ocpi22.ocpi.serializers import InvoicingCallbackSerializer
from ocpi22.util import MyMetadata
from .models import Webhook
from .serializers import WebhookSerializer
from .view_documentation import documentation, common_documentation

callback_serializers = dict(
    INVOICING=InvoicingCallbackSerializer,
    TOKEN_AUTH=MSPAuthorizeCallbackSerializer,
    SESSION=MSPSessionCallbackSerializer,
    CP_STATUS=MSPChargePointStatusCallbackSerializer,
)


class WebhookListCreate(generics.ListCreateAPIView):
    queryset = Webhook.objects.all()
    serializer_class = WebhookSerializer


class WebhookDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Webhook.objects.all()
    serializer_class = WebhookSerializer
    lookup_field = "event"
    metadata = MyMetadata()

    def get_view_description(self, html=False) -> str:
        event = self.kwargs["event"]  # Has to be found
        return format_html(
            markdown.markdown(f"{documentation[event]}{common_documentation}")
        )

    @staticmethod
    def get_webhook_serializer_class(event):
        return callback_serializers.get(event)

    def get_extra_metadata(self, _request) -> dict:
        event = self.kwargs["event"]  # Has to be found
        serializer = self.get_webhook_serializer_class(event)
        outbound_serializer = getattr(serializer, "OutboundSerializer", None)
        response_serializer = getattr(serializer, "ResponseSerializer", None)

        return dict(
            webhook_details=dict(
                data_sent=self.metadata.get_serializer_info(outbound_serializer()),
                expected_response=self.metadata.get_serializer_info(
                    response_serializer()
                )
                if response_serializer
                else _("Response is not parsed"),
            )
        )
