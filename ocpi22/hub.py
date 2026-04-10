from django.http import Http404
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from util import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.ocpi.auth import OCPIPermission
from ocpi22.commands.serializers import (
    StartSessionSerializer,
    StopSessionSerializer,
    UnlockConnectorSerializer,
)
from ocpi22.models.session import Session
from ocpi22.ocpi.util import OCPIResponse, Ocpi, options_message


class CommandsHubViewSet(GenericViewSet):
    # root_view_name = 'commands'
    queryset = (
        Session.objects.none()
    )  # Users who can access Sessions can issue Commands also
    permission_classes = [OCPIPermission]

    def get_serializer_class(self):
        if not hasattr(self, "action_map"):
            return serializers.Serializer
        serializer = dict(
            start_session=StartSessionSerializer,
            stop_session=StopSessionSerializer,
            unlock_connector=UnlockConnectorSerializer,
        ).get(self.action_map["post"])
        return serializer

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f"HUB Command {self.kwargs.get('uid')}"
        if self.name:
            return f"{self.name.capitalize()}"
        return "HUB Commands"

    @action(
        methods=["GET", "POST"],
        detail=False,
        url_name="start-session",
        url_path="START_SESSION",
    )
    def start_session(self, request):
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            serializer = StartSessionSerializer(
                data=request.data, context={"version": request.version}
            )
            if serializer.is_valid():
                # Todo: Forward the OCPI remote command to CPO
                pass
        except (Http404, KeyError) as e:
            return OCPIResponse(
                None,
                status_message=str(e),
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        return OCPIResponse(
            serializer.errors,
            status_message="Please check your request parameters",
            http_status=status.HTTP_400_BAD_REQUEST,
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        )

    @action(methods=["GET", "POST"], detail=False, url_path="STOP_SESSION")
    def stop_session(self, request):
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            serializer = StopSessionSerializer(data=request.data)
            if serializer.is_valid():
                # Forward message
                pass
        except (Http404, KeyError) as e:
            return OCPIResponse(
                None,
                status_message=str(e),
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        return OCPIResponse(
            serializer.errors,
            status_message="Please check your request parameters",
            http_status=status.HTTP_400_BAD_REQUEST,
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        )

    @action(methods=["GET", "POST"], detail=False, url_path="UNLOCK_CONNECTOR")
    def unlock_connector(self, request):
        if not request.data:
            return OCPIResponse(
                {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            serializer = UnlockConnectorSerializer(data=request.data)
            if serializer.is_valid():
                # Forward message
                pass
        except (Http404, KeyError) as e:
            return OCPIResponse(
                None,
                status_message=str(e),
                http_status=status.HTTP_400_BAD_REQUEST,
                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
            )
        return OCPIResponse(
            serializer.errors,
            status_message="Please check your request parameters",
            http_status=status.HTTP_400_BAD_REQUEST,
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        )

    @staticmethod
    def list(request, *_args, **_kwargs):
        return Response(
            dict(
                start_session=request.build_absolute_uri(
                    reverse("commands-start-session")
                ),
                stop_session=request.build_absolute_uri(
                    reverse("commands-stop-session")
                ),
                unlock_connector=request.build_absolute_uri(
                    reverse("commands-unlock-connector")
                ),
            )
        )
