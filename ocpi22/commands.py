from icecream import ic
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.viewsets import GenericViewSet

from ocpi22.api import TokenSerializer
from ocpi22.models import Session, Evse
from ocpi22.sessions import start_session
from ocpi22.util import OCPIResponse


class CommandsSerializer(serializers.Serializer):
    response_url = serializers.URLField()
    token = TokenSerializer()
    location_id = serializers.CharField()
    evse_uid = serializers.CharField(required=False, allow_blank=True)
    authorization_reference = serializers.CharField(required=False, allow_blank=True)


def get_first_connector(evse):
    return evse.connectors.all()[0]


def start_session_async(data):
    ic('Pretended to start session')
    evse = get_object_or_404(Evse, uid=data['evse_id'])
    session = start_session(data['location_id'], evse.uid, get_first_connector(evse), data['token']['uid'])
    return session


class CommandsViewSet(mixins.ListModelMixin, GenericViewSet):
    root_view_name = 'commands'
    queryset = Session.objects.none()  # Users who can access Sessions can issue Commands also
    serializer_class = CommandsSerializer
    # permission_classes = [OCPIPermission]

    @action(methods=['GET', 'POST'], detail=False, url_name='start-session', url_path='START_SESSION')
    def start_session(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            start_session_async(serializer.data)
            return OCPIResponse(serializer.data) # TODO: Return what the OCPI standard says
        return OCPIResponse(serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

    def get_view_name(self):
        return 'Commands'

    @staticmethod
    def get(request):
        return OCPIResponse(dict(juujuu=1))


