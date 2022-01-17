import logging
import os
import uuid

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction, IntegrityError
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend
from icecream import ic
from rest_framework import routers, serializers, status, mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import GenericViewSet

from ocpi22.location import BusinessDetailsSerializer, Coordinate
from ocpi22.models.models import BusinessDetails
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.models.location import Location, Evse
from ocpi22.models.tariff import Tariff, TariffElement, PriceComponent
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.models.cdr import Cdr
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, OCPIPaginationAndHeaders, \
    OCPIResponse, NotOwner, matching_operator, OCPIBadRequestResponse
from ocpi22.versions import get_endpoints_dict
from ocpiconnector.settings import COUNTRY_CODE, PARTY_ID

default_error_messages = dict(
    object_missing='There is no {name} with UID {uid} in our database'
)


class CdrTokenSerializer(serializers.Serializer):
    uid = serializers.CharField(required=True, source='cdr_token_uid')
    type = serializers.ChoiceField(choices=Token.TYPE_CHOICES, required=True, source='cdr_token_type')
    contract_id = serializers.CharField(required=True, source='cdr_token_contract_id')


class TotalCostSerializer(serializers.Serializer):
    excl_vat = serializers.FloatField(source='total_cost_excl_vat')
    incl_vat = serializers.FloatField(source='total_cost_incl_vat', required=False)


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    default_error_messages = default_error_messages
    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']


class PriceComponentSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = PriceComponent
        fields = ('type', 'price', 'vat', 'step_size')

    step_size = serializers.IntegerField(min_value=1, max_value=24*60*60)


class ElementsSaveSerializer(serializers.Serializer):
    price_components = PriceComponentSerializer(many=True)


class TariffSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Tariff
        exclude = ['updated', 'created', 'uid']

    id = serializers.CharField(source='uid', required=False)
    elements = ElementsSaveSerializer(source='tariff_elements', many=True, required=True)
    human_readable = serializers.CharField(source='price', read_only=True)
    # last_updated = serializers.DateTimeField(read_only=False)

    def _delete_children(self, tariff: Tariff) -> None:
        """
        Remove TariffElements and PriceComponents from object - cascade delete should be enabled in Tariff child models
        """

        # noinspection PyUnresolvedReferences
        for te in tariff.tariff_elements.all():
            te.delete()

    def _create_children(self, tariff: Tariff, tariff_elements: dict) -> None:
        for te in tariff_elements:
            price_components = te.pop('price_components')
            # noinspection PyUnresolvedReferences
            tariff_element = TariffElement.objects.create(**te, tariff=tariff)
            for pc in price_components:
                # noinspection PyUnresolvedReferences
                PriceComponent.objects.create(**pc, tariff_element=tariff_element)

    def update(self, instance: Tariff, validated_data: dict) -> Tariff:
        tariff_elements = validated_data.pop('tariff_elements')
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        self._delete_children(instance)
        self._create_children(instance, tariff_elements)
        return instance

    def create(self, validated_data: dict) -> Tariff:
        tariff_elements = validated_data.pop('tariff_elements')
        tariff = Tariff.objects.create(**validated_data)
        self._create_children(tariff, tariff_elements)
        return tariff


class CommandTokenSerializer(serializers.Serializer):
    class Meta:
        fields = ['country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']

    country_code = serializers.CharField(required=True)
    party_id = serializers.CharField(required=True)
    uid = serializers.CharField(required=True)
    type = serializers.ChoiceField(choices=Token.TYPE_CHOICES, required=True)
    contract_id = serializers.CharField(required=True)

    def create(self, validated_data):
        raise NotImplementedError()

    def update(self, instance, validated_data):
        raise NotImplementedError()


class TokenViewSet(mixins.ListModelMixin,
                   GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Token.objects.all().order_by('created')
    serializer_class = TokenSerializer
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'type']

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Token {self.kwargs.get("uid")}'
        if self.name:
            return f'Token detail {self.name.lower()}'
        return f'Tokens'

    @staticmethod
    @transaction.atomic
    def put(request, country_code = None, party_id = None, uid = None):
        data = request.data.get('data', request.data)
        uid = uid or data.get('uid')
        party_id = party_id or data.get('party_id')
        country_code = country_code or data.get('country_code')

        token: Token = Token.get_if_exists(uid=uid, party_id=party_id, country_code=country_code)
        if token and not token.is_owner(request):
            return NotOwner()
        serialiser = TokenSerializer(data=data, instance=token, partial=True)
        if serialiser.is_valid():
            serialiser.save()
            # Return 201 if instance was created
            return OCPIResponse(serialiser.data, http_status=status.HTTP_200_OK if token else status.HTTP_201_CREATED)
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
                    authorization_reference=uuid.uuid4().hex,
                    info=info
                )
            )
        )

    def get(self, request, country_code = None, party_id = None, uid = None):
        if country_code and party_id and uid:
            token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return OCPIResponse(serializer.data)
        return OCPIBadRequestResponse()

    @action(methods=['PUT', 'PATCH'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> OCPIResponse:
        token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)

        # Method is PUT or PATCH
        if not token.is_owner(request):
            return NotOwner()

        method_is_patch = bool(request.method == 'PATCH')

        serializer = TokenSerializer(token,
                                     data=request.data,
                                     partial=method_is_patch,
                                     context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return OCPIResponse(serializer.data)

        return OCPIResponse(errors=serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)


class CdrCoordinatesSerializer(serializers.Serializer):
    def update(self, instance, validated_data):
        raise NotImplementedError()

    def create(self, validated_data):
        raise NotImplementedError()

    latitude = Coordinate(source='cdr_location_latitude')
    longitude = Coordinate(source='cdr_location_longitude')


class CdrLocationSerializer(serializers.Serializer):
    id = serializers.CharField(source='cdr_location_id')
    address = serializers.CharField(source='cdr_location_address')
    city = serializers.CharField(source='cdr_location_city')
    postal_code = serializers.CharField(source='cdr_location_postal_code')
    country = serializers.CharField(source='cdr_location_country')
    coordinates = CdrCoordinatesSerializer(source='*')
    evse_uid = serializers.CharField(source='cdr_location_evse_uid')
    evse_id = serializers.CharField(source='cdr_location_evse_id')
    connector_id = serializers.CharField(source='cdr_location_connector_id')
    connector_standard = serializers.CharField(source='cdr_location_connector_standard')
    connector_format = serializers.CharField(source='cdr_location_connector_format')
    connector_power_type = serializers.CharField(source='cdr_location_connector_power_type')


class CdrSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Cdr
        fields = ['detail_url', 'country_code', 'party_id', 'id', 'start_date_time', 'end_date_time',
                  'session_id', 'cdr_token', 'auth_method', 'authorization_reference',
                  'cdr_location', 'tariffs', 'total_cost', 'total_energy',
                  'total_time', 'credit', 'credit_reference_id', 'last_updated']

    id = serializers.CharField(source='uid')
    cdr_token = CdrTokenSerializer(source='*')
    total_cost = TotalCostSerializer(source='*')
    tariffs = TariffSerializer(many=True)
    cdr_location = CdrLocationSerializer(source='*')

    def create(self, validated_data):
        try:
            tariffs = validated_data.pop('tariffs')
            # ic(tariffs)
            # Todo: Make an archived copy of Tariff and link to the original, clear link when original is changed
            # Link archived copy to Cdr - Jiihaa!
            # Todo: Store Tariffs in an unmutable way
            return super().create(validated_data)
        except IntegrityError as e:
            raise ValidationError(f'A CDR with uid `{validated_data.get("uid")}` already exists. '
                                  'Overwriting an existing CDR is forbidden.')


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

    # Todo: Needs a OCPI standard FI/EON/UID GET (right?)
    @action(methods=['GET'], detail=False, url_name='cdr-by-id',
            url_path='(?P<uid>[^/.]+)')
    def cdr_by_id(self, request, uid) -> Response:
        cdr = get_object_or_404(Cdr, uid=uid)
        serializer = CdrSerializer(cdr, many=False, context={'request': request})
        return OCPIResponse(serializer.data)

    @staticmethod
    @transaction.atomic
    def put(request) -> OCPIResponse:
        data = request.data.get('data', request.data)
        country_code = data.get('country_code')
        party_id = data.get('party_id')

        if not matching_operator(request, country_code, party_id):
            return NotOwner()

        serializer = CdrSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return OCPIResponse(serializer.data, http_status=status.HTTP_201_CREATED)
        return OCPIResponse(errors=serializer.errors)


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

                role, _role_created = CredentialsRole.objects.get_or_create(
                    **data, defaults=dict(business_details=business_details))
                # noinspection PyUnresolvedReferences
                credentials.roles.add(role)
            else:
                return OCPIResponse(serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

        # Delay storing tokens until now, in case the roles have some issue
        credentials.save()

        serializer = CredentialsSerializer(instance=credentials)
        return OCPIResponse(serializer.data)


class LocationIdSerializer(serializers.Serializer):
    location_id = serializers.CharField(required=True)
    default_error_messages = default_error_messages

    def to_representation(self, instance: Session):
        return instance.location.uid

    def to_internal_value(self, data: str):
        location = Location.get_if_exists(uid=data)
        if not location:
            self.fail('object_missing', name='Location', uid=data)
        return dict(location=location)


class EvseUidSerializer(serializers.Serializer):
    evse_uid = serializers.CharField(required=True)
    default_error_messages = default_error_messages

    def to_representation(self, instance: Session):
        return instance.evse.uid

    def to_internal_value(self, data: str):
        evse = Evse.get_if_exists(uid=data)
        if not evse:
            self.fail('object_missing', name='Evse', uid=data)
        return dict(evse=evse)


class SessionSaveSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Session
        fields = ['detail_url', 'country_code', 'party_id', 'uid',
                  'start_date_time', 'end_date_time', 'kwh',
                  'cdr_token', 'auth_method', 'authorization_reference',
                  'location_id', 'evse_uid', 'connector_id', 'meter_id', 'currency', 'total_cost',
                  'status', 'last_updated']

    cdr_token = CdrTokenSerializer(required=True, source='*')
    location_id = LocationIdSerializer(source='*')
    evse_uid = EvseUidSerializer(source='*')
    total_cost = TotalCostSerializer(source='*', required=False)

    def create(self, validated_data):
        return Session.objects.create(
            **validated_data
        )

    def update(self, instance, validated_data):
        for key, value in validated_data.items():
            if key not in ('uid', 'location', 'evse'):
                setattr(instance, key, value)
            else:
                print(f'Skipping key {key}')
        instance.save()
        return instance


# class TariffSaveSerializer(HyperlinkedModelSerializerCleanedUp):
#     class Meta:
#         model = Tariff
#         fields = ('country_code', 'party_id', 'id', 'type',
#                   'tariff_alt_url', 'elements',
#                   'last_updated')
#
#     id = serializers.CharField(source='uid')
#     elements = ElementsSaveSerializer(write_only=True, validators=[])
#
#     @transaction.atomic
#     def create(self, validated_data):
#         elements = validated_data.pop('elements')
#         price_components = elements.pop('price_components')
#         tariff = Tariff.objects.create(**validated_data)
#         for pc in price_components:
#             # noinspection PyUnresolvedReferences
#             price_component = PriceComponent.objects.create(**pc, tariff=tariff)
#         return tariff
#
#     @transaction.atomic
#     def update(self, tariff, validated_data):
#         # ic()
#         elements = validated_data.pop('elements')
#         price_components = elements.pop('price_components')
#         for key, value in validated_data.items():
#             setattr(tariff, key, value)
#
#         tariff.price_components.all().delete()
#
#         for pc in price_components:
#             # ic(pc)
#             # noinspection PyUnresolvedReferences
#             price_component = PriceComponent.objects.create(**pc, tariff=tariff)
#             # ic(price_component)
#
#         tariff.save()
#         return tariff


class TariffViewSet(mixins.RetrieveModelMixin,
                    mixins.ListModelMixin,
                    GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Tariff.objects.exclude(archived=True).order_by('created')
    serializer_class = TariffSerializer
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'

    def get_view_name(self):
        return 'Tariffs'

    @action(methods=['GET'], detail=False, description='Get a single Tariff by country, party and uid',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code, party_id, uid) -> Response:
        tariff = get_object_or_404(Tariff, country_code=country_code, party_id=party_id, uid=uid, archived=False)
        serializer = TariffSerializer(tariff, many=False, context={'request': request})
        return OCPIResponse(serializer.data)

    @staticmethod
    @transaction.atomic
    def put(request, country_code=None, party_id=None, uid=None) -> OCPIResponse:
        # This PUT is used both for the Tariff endpoint root and the path with country_code, party_id and Tariff uid
        data = request.data.get('data', request.data)
        country_code = country_code or data.get('country_code')
        party_id = party_id or data.get('party_id')
        uid = uid or data.get('id')

        if not matching_operator(request, country_code, party_id):
            return NotOwner()

        # noinspection PyUnresolvedReferences
        try:
            # noinspection PyUnresolvedReferences
            tariff = Tariff.objects.get(country_code=country_code, party_id=party_id, uid=uid,
                                        archived=False)
        except Tariff.DoesNotExist:
            tariff = None
        serializer = TariffSerializer(instance=tariff, data=data)
        if serializer.is_valid():
            serializer.save()
            return OCPIResponse(serializer.data, http_status=status.HTTP_200_OK if tariff else status.HTTP_201_CREATED)
        else:
            return OCPIResponse(errors=serializer.errors)


class SessionViewSet(mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'status', 'meter_id', 'cdr_token_uid', 'authorization_reference']
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'
    # noinspection PyUnresolvedReferences
    queryset = Session.objects.all().order_by('created')
    serializer_class = SessionSaveSerializer

    @transaction.atomic
    @action(methods=['GET'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def session_by_id(self, request, country_code, party_id, uid) -> Response:
        # noinspection PyUnresolvedReferences
        session = get_object_or_404(Session, country_code=country_code, party_id=party_id, uid=uid)

        if request.method == 'GET':
            serializer = SessionSaveSerializer(session, context={'request': request})
            return OCPIResponse(serializer.data)

        # elif request.method == 'PATCH':
        #     serializer = SessionSerializer(session, data=request.data, partial=True, context={'request': request})
        #     if serializer.is_valid():
        #         serializer.save()
        #         return OCPIResponse(serializer.data)
        #     else:
        #         return OCPIResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return OCPIResponse(http_status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    @transaction.atomic
    def put(request, partial=False) -> OCPIResponse:
        data = request.data.get('data', request.data)
        uid = data.get('uid')
        country_code = data.get('country_code')
        party_id = data.get('party_id')

        session: Session = Session.get_if_exists(uid=uid, party_id=party_id, country_code=country_code)
        if session and not session.is_owner(request):
            return NotOwner()
        serialiser = SessionSaveSerializer(data=request.data, instance=session, partial=partial)
        if serialiser.is_valid():
            serialiser.save()
            return OCPIResponse(serialiser.data,
                                http_status=status.HTTP_200_OK if session else status.HTTP_201_CREATED)
        return OCPIResponse(errors=serialiser.errors, http_status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        return self.put(request, partial=True)


class RootView(routers.APIRootView):
    """
    Welcome to the OCPI Connector Developer Central. Here you can access the OCPI 2.2 endpoints with examples
    and the CPO interface for quick integration to popular roaming networks.
    """

    @staticmethod
    def get(request: WSGIRequest, **kwargs):
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

    @staticmethod
    def get(request, **kwargs):
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
