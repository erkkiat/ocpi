import os

from django.db import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import routers, serializers, status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet
from rest_framework.exceptions import NotFound

from ocpi22.location import BusinessDetailsSerializer
from ocpi22.models import Token, Tariff, Session, Cdr, Credentials, CredentialsRole, BusinessDetails
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, OCPIPaginationAndHeaders, get_total_cost, clear_empty, \
    OCPIResponse
from ocpi22.versions import get_endpoints_dict
from ocpiconnector.settings import COUNTRY_CODE, PARTY_ID


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']


class CdrTokenSerializer(HyperlinkedModelSerializerCleanedUp):
    """
    Used for showing limited Token information when serializing a CDR
    """

    class Meta:
        model = Token
        fields = ['uid', 'type', 'contract_id']


class TokenViewSet(mixins.UpdateModelMixin,
                   mixins.RetrieveModelMixin,
                   mixins.ListModelMixin,
                   GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'type']

    # def options(self, request, *args, **kwargs):
    #     ic(args, kwargs)
    #     if not kwargs:
    #         return Response(dict(message='There is no options for this view, please see options for the Token view'))
    #     else:
    #         return super().options(request, *args, **kwargs)

    def get_view_name(self):
        return 'Tokens'

    @staticmethod
    def put(request):
        serialiser = TokenSerializer(data=request.data)
        if serialiser.is_valid():
            serialiser.save()
        return Response(serialiser.data)

    # noinspection PyUnresolvedReferences
    @action(methods=['GET', 'PUT', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)
        method_is_patch = True if request.method == 'PATCH' else False

        if request.method == 'GET':
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return OCPIResponse(serializer.data)

        elif request.method in ('PUT', 'PATCH'):
            serializer = TokenSerializer(token,
                                         data=request.data,
                                         partial=method_is_patch,
                                         context={'request': request})
            if serializer.is_valid():
                serializer.save()
                return OCPIResponse(serializer.data)
            else:
                return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)


class CdrSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Cdr
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'start_date_time', 'end_date_time',
                  'session_id', 'cdr_token', 'auth_method', 'authorization_reference',
                  'cdr_location', 'tariffs', 'total_cost', 'total_energy',
                  'total_time', 'credit', 'credit_reference_id', 'last_updated']

    cdr_token = CdrTokenSerializer(read_only=True)
    total_cost = serializers.SerializerMethodField()
    tariffs = serializers.SerializerMethodField()

    @staticmethod
    def get_total_cost(obj):
        return get_total_cost(obj)

    @staticmethod
    def get_tariffs(cdr):
        return [t.uid for t in cdr.tariffs.all()]


class CdrViewSet(mixins.RetrieveModelMixin,
                 mixins.ListModelMixin,
                 GenericViewSet):
    """
    These are the Charge Detail Records. Once a CDR is created, it must not be modified or removed.
    A CDR can be credited to the customer by creating a credit CDR in the admin user interface.
    """
    # noinspection PyUnresolvedReferences
    queryset = Cdr.objects.all().order_by('created')
    serializer_class = CdrSerializer
    pagination_class = OCPIPaginationAndHeaders

    @action(methods=['GET'], detail=False, url_name='cdr-by-id',
            url_path='(?P<uid>[^/.]+)')
    def cdr_by_id(self, request, uid) -> Response:
        cdr = get_object_or_404(Cdr, uid=uid)
        serializer = CdrSerializer(cdr, many=False, context={'request': request})
        return OCPIResponse(serializer.data)


class RolesSerializer(serializers.ModelSerializer):
    class Meta:
        model = CredentialsRole
        fields = ('country_code', 'party_id', 'role', 'business_details')

    business_details = BusinessDetailsSerializer()


class CredentialsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Credentials
        fields = ('token', 'url', 'roles')

    token = serializers.CharField(source='theirs')
    url = serializers.URLField()
    roles = RolesSerializer(many=True)

    # noinspection PyUnresolvedReferences
    def create(self, validated_data):
        try:
            roles = validated_data.pop('roles')
            credentials = Credentials.objects.create(**validated_data)
            for role_dict in roles:
                business_details_dict = role_dict.pop('business_details')
                business_details = BusinessDetails.objects.create(**business_details_dict)
                CredentialsRole.objects.create(credentials=credentials,
                                               business_details=business_details,
                                               **role_dict)
            return credentials
        except IntegrityError:
            raise NotFound(code=405, detail='This Credentials already exists. Try doing a PUT or DELETE.')


class CredentialsViewSet(mixins.CreateModelMixin,
                         GenericViewSet):
    """
    Credential tokens exchange. Please note that the tokens are always base64 encoded for transport.
    """
    # The queryset tells Django REST how to determine access to these endpoints
    # noinspection PyUnresolvedReferences
    queryset = Credentials.objects.none()
    serializer_class = CredentialsSerializer

    def get_view_name(self):
        return 'Credentials'

    @staticmethod
    def get(request):
        return Response(
            dict(
                token=request.credentials.ours_base64()
                if hasattr(request, 'credentials') else 'not available when using basic auth',

                url=request.build_absolute_uri(reverse('base-versions')),

                roles=[dict(
                    role='CPO',
                    country_code=COUNTRY_CODE,
                    party_id=PARTY_ID,
                    business_details=dict(
                        name=os.environ.get('BUSINESS_NAME', 'Please set BUSINESS_NAME in server environment')
                    )
                )]
            )
        )


class SessionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['detail_url', 'country_code', 'party_id', 'uid',
                  'start_date_time', 'end_date_time', 'kwh',
                  'cdr_token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'meter_id', 'currency', 'total_cost',
                  'status', 'last_updated']

    uid = serializers.CharField(read_only=True)
    cdr_token = serializers.SerializerMethodField()
    location_id = serializers.SerializerMethodField()
    evse_uid = serializers.SerializerMethodField()
    connector_id = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()

    @staticmethod
    def get_cdr_token(session):
        token = session.cdr_token
        return clear_empty(dict(
            uid=token.uid,
            type=token.type,
            contract_id=token.contract_id
        ))

    @staticmethod
    def get_location_id(session):
        return session.location.uid

    @staticmethod
    def get_evse_uid(session):
        return session.evse.uid

    @staticmethod
    def get_connector_id(session):
        return session.connector.uid

    @staticmethod
    def get_total_cost(obj):
        return get_total_cost(obj)


class TariffSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Tariff
        fields = ('detail_url', 'readable', 'country_code', 'party_id', 'id', 'type',
                  'tariff_alt_url', 'elements', 'last_updated')

    id = serializers.CharField(source='uid', read_only=True)
    elements = serializers.SerializerMethodField()
    readable = serializers.SerializerMethodField()

    @staticmethod
    def get_elements(tariff: Tariff) -> dict:
        # noinspection PyUnresolvedReferences
        price_components = [
            dict(
                type=pc.type,
                price=pc.price,
                vat=pc.vat,
                step_size=pc.step_size
            )
            for pc in tariff.price_components.all()
        ]
        for pc in price_components:
            if not pc.get('vat'):
                pc.pop('vat')
        return dict(price_components=price_components)

    @staticmethod
    def get_readable(tariff: Tariff) -> str:
        return str(tariff)


class TariffViewSet(mixins.RetrieveModelMixin,
                    mixins.ListModelMixin,
                    GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Tariff.objects.all().order_by('created')
    serializer_class = TariffSerializer
    pagination_class = OCPIPaginationAndHeaders

    def get_view_name(self):
        return 'Tariffs'

    # Todo: Create a completely new object using PUT

    @action(methods=['GET'], detail=False, description='Get a single Tariff by country, party and uid',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        tariff = get_object_or_404(Tariff, country_code=country_code, party_id=party_id, uid=uid)
        serializer = TariffSerializer(tariff, many=False, context={'request': request})
        return OCPIResponse(serializer.data)


class SessionViewSet(mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'status', 'meter_id', 'cdr_token', 'authorization_reference']
    pagination_class = OCPIPaginationAndHeaders

    @action(methods=['GET'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def session_by_id(self, request, country_code, party_id, uid) -> Response:
        # noinspection PyUnresolvedReferences
        session = get_object_or_404(Session, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = SessionSerializer(session, context={'request': request})
            return OCPIResponse(serializer.data)

        # elif request.method == 'PATCH':
        #     serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
        #     if serializer.is_valid():
        #         serializer.save()
        #         return OCPIResponse(serializer.data)
        #     else:
        #         return OCPIResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)

    # noinspection PyUnresolvedReferences
    queryset = Session.objects.all().order_by('created')
    serializer_class = SessionSerializer


class OcpiApi22View(routers.APIRootView):
    """
    This portal provides ways to view the information in the database, to read the API documentation and
    to try out sending requests to the API.

    The streamlined interfaces for the CPO are available at [/api/cpo/v1/](/api/cpo/v1/).
    You can contact [support@chargerhub.eu](support@chargerhub.eu) for training.
    """

    def get(self, request, **kwargs):
        return Response(get_endpoints_dict(request))

    def get_view_name(self):
        return 'OCPI 2.2'


class OCPIRouter(routers.DefaultRouter):
    APIRootView = OcpiApi22View
    root_view_name = 'ocpi-22'
