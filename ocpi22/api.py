import logging
import os
import uuid

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend
from icecream import ic
from rest_framework import routers, serializers, status, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.location import BusinessDetailsSerializer
from ocpi22.models import Token, Tariff, Session, Cdr, Credentials, CredentialsRole, BusinessDetails
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, OCPIPaginationAndHeaders, get_total_cost, clear_empty, \
    OCPIResponse, NotOwner
from ocpi22.versions import get_endpoints_dict
from ocpiconnector.settings import COUNTRY_CODE, PARTY_ID


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']


# class CdrTokenSerializer(serializers.Serializer):
#     """
#     Used for showing limited Token information when serializing a CDR
#     """
#
#     class Meta:
#         model = Token
#         fields = ['uid', 'type', 'contract_id']


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
        uid = request.data.get('uid')
        party_id = request.data.get('party_id')

        token: Token = Token.get_if_exists(uid=uid, party_id=party_id)
        if token and not token.is_owner(request):
            return NotOwner()
        serialiser = TokenSerializer(data=request.data, instance=token, partial=True)
        if serialiser.is_valid():
            serialiser.save()
            # Return 201 if instance was created
            return OCPIResponse(serialiser.data, http_status=200 if token else 201)
        else:
            return OCPIResponse(errors=serialiser.errors, http_status=status.HTTP_400_BAD_REQUEST)

    # Todo: NO_CREDIT and other errors should go all the way back to the charger to be shown
    @csrf_exempt
    @action(methods=['POST', 'GET'], detail=False,
            url_path='(?P<token_uid>[^/.]+)/authorize')
    def authorize(self, request: Request, token_uid) -> OCPIResponse:
        assert settings.DEBUG, 'Simulator endpoints work only in debug mode. Try exchanging Credentials again.'
        ic(request.data, request.get_full_path())
        token = get_object_or_404(Token, uid=token_uid)
        allowed = Token.ALLOWED
        info = ''
        if not token.valid:
            allowed = Token.EXPIRED
            info = 'Your token is no longer valid'
        elif 'NO_CREDIT' in token_uid:
            allowed = Token.NO_CREDIT
            info = 'You have insufficient balance on your account'
        serializer = TokenSerializer(instance=token)
        return OCPIResponse(
            dict(
                AuthorizationInfo=dict(
                    allowed=allowed,
                    token=serializer.data,
                    authorization_reference=uuid.uuid4(),
                    info=info
                )
            )
        )

    @action(methods=['GET', 'PUT', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> OCPIResponse:
        token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)
        method_is_patch = True if request.method == 'PATCH' else False

        if request.method == 'GET':
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return OCPIResponse(serializer.data)

        elif request.method in ('PUT', 'PATCH'):
            if not token.is_owner(request):
                return NotOwner()

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

    cdr_token = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()
    tariffs = serializers.SerializerMethodField()
    cdr_location = serializers.SerializerMethodField()

    @staticmethod
    def get_total_cost(obj):
        return get_total_cost(obj)

    @staticmethod
    def get_tariffs(cdr):
        return [t.uid for t in cdr.tariffs.all()]

    @staticmethod
    def get_cdr_token(cdr):
        return dict(
            uid=cdr.cdr_token_uid,
            type=cdr.cdr_token_type,
            contract_id=cdr.cdr_token_contract_id
        )

    @staticmethod
    def get_cdr_location(cdr):
        result = dict(
            id=cdr.cdr_location_id,
            address=cdr.cdr_location_address,
            city=cdr.cdr_location_city,
            postal_code=cdr.cdr_location_postal_code,
            country=cdr.cdr_location_country,
            coordinates=dict(
                latitude=cdr.cdr_location_latitude,
                longitude=cdr.cdr_location_longitude
            ),
            evse_uid=cdr.cdr_location_evse_uid,
            evse_id=cdr.cdr_location_evse_id,
            connector_id=cdr.cdr_location_connector_id,
            connector_standard=cdr.cdr_location_connector_standard,
            connector_format=cdr.cdr_location_connector_format,
            connector_power_type=cdr.cdr_location_connector_power_type,
        )
        return result


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
    # def create(self, validated_data):
    #     try:
    #         roles = validated_data.pop('roles')
    #         credentials = Credentials.objects.create(**validated_data)
    #         for role_dict in roles:
    #             business_details_dict = role_dict.pop('business_details')
    #             business_details = BusinessDetails.objects.create(**business_details_dict)
    #             CredentialsRole.objects.create(credentials=credentials,
    #                                            business_details=business_details,
    #                                            **role_dict)
    #         return credentials
    #     except IntegrityError:
    #         raise NotFound(code=405, detail='This Credentials already exists. Try doing a PUT or DELETE.')


class CredentialsViewSet(mixins.CreateModelMixin,
                         GenericViewSet):
    """
    Credential tokens exchange. Please note that the tokens are base64 encoded for transport, except in the
    credentials exchange module. For testing purposes, you can include the token by using
    ?auth-test=TOKEN.
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

                # Todo: Check this, should be "Retrieves the credentials object to access the server’s platform"
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

    @staticmethod
    def delete(request: Request, *_args, **_kwargs):
        # Todo: Make sure deletition is not possible for others than owner
        if not hasattr(request, 'credentials'):
            return OCPIResponse("There seem to be no credentials in use for this request.")
        logging.warning(f'Deleting {request.credentials} on request by Credential owner.')
        request.credentials.delete()
        return OCPIResponse(status_message='Your credentials have been deleted, as requested.')

    def create(self, request: Request, *args, **kwargs):
        assert hasattr(request, 'credentials')
        # noinspection PyUnresolvedReferences
        data = request.data
        credentials: Credentials = request.credentials
        credentials.theirs = data.get('token')
        credentials.url = data.get('url')
        # noinspection PyUnresolvedReferences
        credentials.roles.all().delete()

        for role in data['roles']:
            assert isinstance(role, dict)
            serializer = RolesSerializer(data=role)
            if serializer.is_valid():
                # They should definitely not have the same operator ID as we do
                # ic(serializer.data, settings.COUNTRY_CODE, settings.PARTY_ID)
                if serializer.data.get('country_code') == settings.COUNTRY_CODE \
                  and serializer.data.get('party_id') == settings.PARTY_ID:
                    return OCPIResponse(status_message=f'You are not allowed to use the same operator ID '
                                        f'"{settings.COUNTRY_CODE}*{settings.PARTY_ID}" as we do.',
                                        http_status=status.HTTP_400_BAD_REQUEST, status_code=2001)

                data = serializer.data
                bd = data.pop('business_details')
                business_details, _businessdetails_created = BusinessDetails.objects.get_or_create(**bd)

                role, _role_created = CredentialsRole.objects.get_or_create(**data)
                credentials.roles.add(role)
                role.business_details = business_details
            else:
                return OCPIResponse(serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

        # Delay storing tokens until now, in case the roles have some issue
        credentials.save()

        serializer = CredentialsSerializer(instance=credentials)
        return OCPIResponse(serializer.data)


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
        return clear_empty(dict(
            uid=session.cdr_token_uid,
            type=session.cdr_token_type,
            contract_id=session.cdr_token_contract_id
        ))

    @staticmethod
    def get_location_id(session):
        return session.location.uid

    @staticmethod
    def get_evse_uid(session):
        return session.evse.uid

    @staticmethod
    def get_connector_id(session):
        return session.connector.uid if session.connector else 0

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
    filterset_fields = ['country_code', 'party_id', 'status', 'meter_id', 'cdr_token_uid', 'authorization_reference']
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


class RootView(routers.APIRootView):
    """
    Welcome to the OCPI Connector Developer Central. Here you can access the OCPI 2.2 endpoints with examples
    and the CPO interface for quick integration to popular roaming networks.
    """

    def get(self, request: WSGIRequest, **kwargs):
        return Response({
            "OCPI 2.2": request.build_absolute_uri(reverse('ocpi-22')),
            "CPO API": request.build_absolute_uri(reverse('cpo-api')),
        })

    def get_view_name(self):
        return 'OCPI Connector Developer Central'


class RootRouter(routers.DefaultRouter):
    APIRootView = RootView
    root_view_name = 'root'


class OcpiApi22View(routers.APIRootView):
    """
    This portal provides ways to test OCPI 2.2 interaction, view the information in the database and
    to read the API documentation.

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

    # Make trailing slash optional in URLs
    def __init__(self):
        super().__init__()
        self.trailing_slash = '/?'
