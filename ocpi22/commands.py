from django.http import Http404
from icecream import ic
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.viewsets import GenericViewSet

from ocpi22.api import TokenSerializer
from ocpi22.models import Session, Evse
from ocpi22.sessions import create_session
from ocpi22.util import OCPIResponse, Ocpi


class CommandsSerializer(serializers.Serializer):
    response_url = serializers.URLField()
    token = TokenSerializer()
    location_id = serializers.CharField()
    evse_uid = serializers.CharField(required=False, allow_blank=True)
    authorization_reference = serializers.CharField(required=False, allow_blank=True)


class DisplayTextSerializer(serializers.Serializer):
    # Language Code ISO 639-1.
    language = serializers.CharField(max_length=2)

    # Text to be displayed to a end user. No markup, html etc. allowed.
    text = serializers.CharField(max_length=512)


class CommandResponse(serializers.Serializer):

    RESULT_OPTIONS = (
        'NOT_SUPPORTED',    # The requested command is not supported by this CPO, Charge Point, EVSE etc.
        'REJECTED',         # Command request rejected by the CPO.
                            # (Session might not be from a customer of the eMSP that send this request)
        'ACCEPTED',         # Command request accepted by the CPO.
        'UNKNOWN_SESSION'   # The Session in the requested command is not known by this CPO.
    )

    # Response from the CPO on the command request.
    result = serializers.CharField()

    # Timeout for this command in seconds. When the Result is not received within this timeout,
    # the eMSP can assume that the message might never be send.
    timeout = serializers.IntegerField()

    # Human-readable description of the result (if one can be provided), multiple languages can be provided.
    # message = DisplayTextSerializer()


def start_session(data):
    ic(data)
    ic('Pretended to start session')
    evse = get_object_or_404(Evse, uid=data['evse_uid'])
    session = create_session(
        data['location_id'],
        evse.uid,
        1,  # Todo: Get connector ID from CPO system
        ad_hoc_token=data['token'],
        authorize=False  # When eMSP sends a SESSION_START, they are responsible for validating their Token
    )
    return session


class CommandsViewSet(mixins.ListModelMixin, GenericViewSet):
    root_view_name = 'commands'
    queryset = Session.objects.none()  # Users who can access Sessions can issue Commands also
    serializer_class = CommandsSerializer
    # permission_classes = [OCPIPermission]

    @action(methods=['GET', 'POST'], detail=False, url_name='start-session', url_path='START_SESSION')
    def start_session(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            if serializer.is_valid():
                result = 'REJECTED'
                session = start_session(serializer.data)
                if session:
                    result = 'ACCEPTED'
                response_serializer = CommandResponse(
                    instance=dict(
                        result=result,
                        timeout=5,
                        # message=DisplayTextSerializer(
                        #     instance=dict(
                        #         language='EN',
                        #         text='Command accepted'
                        #     ))
                    ))
                return OCPIResponse(response_serializer.data)
        except (NotFound, Http404) as e:
            return OCPIResponse(None, status_message=str(e),
                                http_status=status.HTTP_400_BAD_REQUEST,
                                status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
        return OCPIResponse(serializer.errors,
                            http_status=status.HTTP_400_BAD_REQUEST,
                            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)

    def get_view_name(self):
        return 'Commands'

    @staticmethod
    def get(_request):
        return OCPIResponse(dict(juujuu=1))


