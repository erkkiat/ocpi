import logging
import os
import uuid
from typing import Union, Optional

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

from ocpi22.cpo_api import CHARGER
from ocpi22.location import BusinessDetailsSerializer, Coordinate
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.tariff import Tariff, TariffElement, PriceComponent
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.models.cdr import Cdr
from ocpi22.util import HyperlinkedModelSerializerCleanedUp, matching_operator
from ocpi22.ocpi_util import OCPIBadRequestResponse, NotOwner, OCPIResponse, Ocpi, OCPIPaginationAndHeaders
from ocpi22.versions import get_endpoints_dict
from ocpiconnector.management.commands.exchange_credentials import get_our_roles
from ocpiconnector.ocpi_identities import ocpi_platform

default_error_messages = dict(
    object_missing='There is no {name} with UID `{uid}` in our database'
)


# Todo: In case a PATCH request fails, the client is expected to call the GET method to check the state
#  of the object in the other party’s system. If the object doesn’t exist, the client should do a PUT.

# Todo: Only requests/responses from Function Modules: such as: Tokens, Locations, CDRs etc. SHALL be routed,
#  so need the routing headers.


class CdrTokenSerializer(serializers.Serializer):
    uid = serializers.CharField(required=True, source='cdr_token_uid')
    type = serializers.ChoiceField(choices=Token.TYPE_CHOICES, required=True, source='cdr_token_type')
    contract_id = serializers.CharField(required=True, source='cdr_token_contract_id')


class TotalCostSerializer(serializers.Serializer):
    excl_vat = serializers.FloatField(source='total_cost_excl_vat', required=False)
    incl_vat = serializers.FloatField(source='total_cost_incl_vat', required=False)


class TokenSerializer(HyperlinkedModelSerializerCleanedUp):
    default_error_messages = default_error_messages

    class Meta:
        model = Token
        fields = ['detail_url', 'country_code', 'party_id', 'uid', 'type',
                  'contract_id', 'visual_number', 'issuer', 'group_id',
                  'valid', 'whitelist', 'language', 'default_profile_type', 'last_updated']

    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)


class PriceComponentSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = PriceComponent
        fields = ('type', 'price', 'vat', 'step_size')

    step_size = serializers.IntegerField(min_value=1, max_value=24 * 60 * 60)


class ElementsSaveSerializer(serializers.Serializer):
    price_components = PriceComponentSerializer(
        many=True,
        label=f'See {settings.OCPI_SPECIFICATION_URL}mod_tariffs.asciidoc#mod_tariffs_pricecomponent_class'
    )


class TariffSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Tariff
        exclude = ['updated', 'created', 'uid', 'archived']

    id = serializers.CharField(source='uid', required=False, label='Preferably a human readable, unique identifier')
    elements = ElementsSaveSerializer(
        source='tariff_elements', many=True, required=True,
        label=f'See {settings.OCPI_SPECIFICATION_URL}mod_tariffs.asciidoc#mod_tariffs_tariffelement_class'
    )
    human_readable = serializers.CharField(source='price', read_only=True,
                                           label='This non-OCPI field exists for educational purposes')
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

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
            tariff_element = TariffElement.objects.create(**te, tariff=tariff)
            for pc in price_components:
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
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

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
            return f'{self.name.capitalize()}'
        return f'Tokens'

    @staticmethod
    def get_object(uid=None) -> Optional[Token]:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Token, uid=uid)

    @staticmethod
    @transaction.atomic
    def put(request, country_code=None, party_id=None, uid=None):
        data = request.data.get('data', request.data)
        uid = uid or data.get('uid')
        party_id = party_id or data.get('party_id')
        country_code = country_code or data.get('country_code')

        token: Token = Token.get_if_exists(uid=uid, party_id=party_id, country_code=country_code)
        if token and not token.is_owner(request):
            return NotOwner()
        serialiser = TokenSerializer(data=data, instance=token, partial=True)
        if serialiser.is_valid():
            new_token = serialiser.save()
            if ocpi_platform.is_cpo:
                CHARGER.add_or_update_token(new_token.uid, new_token.valid, created=bool(token))
            Token.send_hub_updates(serialiser.data)
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

    def get(self, request, country_code=None, party_id=None, uid=None):
        if country_code and party_id and uid:
            token = get_object_or_404(Token, country_code=country_code, party_id=party_id, uid=uid)
            serializer = TokenSerializer(token, many=False, context={'request': request})
            return OCPIResponse(serializer.data)
        return OCPIBadRequestResponse()

    @action(methods=['PUT', 'PATCH'], detail=False, url_name='by-id',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def token_by_id(self, request, country_code, party_id, uid) -> OCPIResponse:
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
    name = serializers.CharField(source='cdr_location_name', required=False)
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
                  'cdr_location', 'tariffs', 'total_cost', 'total_energy', 'currency',
                  'total_time', 'credit', 'credit_reference_id', 'last_updated']

    id = serializers.CharField(source='uid')
    cdr_token = CdrTokenSerializer(source='*')
    total_cost = TotalCostSerializer(source='*')
    tariffs = TariffSerializer(many=True, required=True)
    cdr_location = CdrLocationSerializer(source='*')
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)
    start_date_time = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=True)
    end_date_time = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=True)

    def create(self, validated_data):
        try:
            tariffs = validated_data.pop('tariffs')
            tariff_serializer = TariffSerializer()
            tariff_list = []
            for t in tariffs:
                t['archived'] = True
                tariff_list.append(tariff_serializer.create(t))
            cdr = Cdr.objects.create(**validated_data)
            cdr.tariffs.set(tariff_list)
            return cdr
        except IntegrityError as e:
            raise ValidationError(f'A CDR with uid `{validated_data.get("uid")}` already exists. '
                                  'Overwriting an existing CDR is forbidden.')


class CdrViewSet(mixins.ListModelMixin,
                 GenericViewSet):
    """
    These are the records created for the purpose of billing. Once a CDR is created, it must not be modified or removed.
    A CDR can be credited to the customer by creating a credit CDR in the admin tools.
    **VISIBILITY**: A CDR record is only available to relevant parties,
    so fetching another party's CDR should not be allowed. (When logged in as a superuser, you can see all CDRs)
    """
    # noinspection PyUnresolvedReferences
    queryset = Cdr.objects.none()  # Default to no visibility, fine tune with get_queryset()
    serializer_class = CdrSerializer
    pagination_class = OCPIPaginationAndHeaders

    def get_queryset(self):
        if self.request.user.is_superuser:
            # noinspection PyUnresolvedReferences
            return Cdr.objects.all().order_by('created')
        if hasattr(self.request, 'country_code'):
            ic(self.request.country_code, self.request.party_id)
            # noinspection PyUnresolvedReferences
            return Cdr.objects.filter(
                country_code=self.request.country_code,
                party_id=self.request.party_id
            ).order_by('created')
        # noinspection PyUnresolvedReferences
        return Cdr.objects.none()

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'CDR {self.kwargs.get("uid")}'
        if self.name:
            return f'CDR {self.name.lower()}'
        return f'Charge Detail Records'

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None

    @action(methods=['GET'], detail=False,
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)')
    def by_id(self, request, country_code=None, party_id=None, uid=None) -> Response:
        cdr = get_object_or_404(Cdr, country_code=country_code, party_id=party_id, uid=uid)
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

        # tariffs = data.pop('tariffs', [])
        # ic(data)
        # ic(tariffs)
        tariff_list = []
        # for t in tariffs:
        #     ic(t)
        #     tariff = Tariff.get_if_exists(uid=t.get('uid', None))
        #     if not tariff:
        #         tariff_serializer = TariffSerializer(data=t)
        #         if tariff_serializer.is_valid():
        #             tariff = tariff_serializer.save()
        #     tariff_list.append(tariff)
        # ic(data)
        serializer = CdrSerializer(data=data)
        if serializer.is_valid():
            cdr = serializer.save()
            # cdr.tariffs.set(tariff_list)
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
                roles=get_our_roles(),
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
                data = serializer.data
                bd = data.pop('business_details')
                business_details, _businessdetails_created = BusinessDetails.objects.get_or_create(
                    name=bd.get('name'), website=bd.get('website', ''), defaults=dict(logo=bd.get('logo', ''))
                )

                role, _role_created = CredentialsRole.objects.get_or_create(
                    **data, defaults=dict(business_details=business_details))
                # noinspection PyUnresolvedReferences
                credentials.roles.add(role)
            else:
                return OCPIResponse(serializer.errors, http_status=status.HTTP_400_BAD_REQUEST)

        # Delay storing tokens until now, in case the roles have some issue
        credentials.save()
        serializer = CredentialsSerializer(instance=credentials)

        if not credentials.is_complete():
            # Let's respond, we are only half way through
            from ocpi22 import tasks
            tasks.exchange_credentials.apply_async(
                (credentials.token_a, credentials.url),
                countdown=2,
                retry=True, retry_policy=dict(max_retries=5, interval_start=2))

        return OCPIResponse(serializer.data)


class LocationIdSerializer(serializers.CharField):
    # location_id = serializers.CharField(required=True)
    default_error_messages = default_error_messages

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def to_representation(self, instance: Union[Session, Location]):
        if isinstance(instance, Session): return instance.location.uid
        if isinstance(instance, dict): instance = instance.get('location')
        if instance:
            return instance.uid

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


class ConnectorIdSerializer(serializers.Serializer):
    default_error_messages = default_error_messages

    def to_representation(self, instance: Session):
        return instance.connector.uid if hasattr(instance, 'connector') and instance.connector else None

    def to_internal_value(self, data: str):
        connector = Connector.get_if_exists(uid=data)
        if not connector:
            self.fail('object_missing', name='Connector', uid=data)
        return dict(connector=connector)


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
    connector_id = ConnectorIdSerializer(source='*', required=False)
    total_cost = TotalCostSerializer(source='*', required=False)
    last_updated = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ", required=False)

    def create(self, validated_data):
        # noinspection PyUnresolvedReferences
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


class TariffViewSet(mixins.ListModelMixin,
                    GenericViewSet):
    # noinspection PyUnresolvedReferences
    queryset = Tariff.objects.exclude(archived=True).order_by('created')
    serializer_class = TariffSerializer
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Tariff {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return 'Tariffs'

    @action(methods=['GET'], detail=False, description='Get a single Tariff by country, party and uid',
            url_path='(?P<country_code>[^/.]+)/(?P<party_id>[^/.]+)/(?P<uid>[^/.]+)', url_name='by-id')
    def tariff_by_id(self, request, country_code, party_id, uid) -> Response:
        tariff = get_object_or_404(Tariff, country_code=country_code, party_id=party_id, uid=uid, archived=False)
        serializer = TariffSerializer(tariff, many=False, context={'request': request})
        return OCPIResponse(serializer.data)

    @staticmethod
    def get_object(uid=None) -> Tariff:
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Tariff, uid=uid)

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
            Tariff.send_hub_updates(data)
            return OCPIResponse(serializer.data, http_status=status.HTTP_200_OK if tariff else status.HTTP_201_CREATED)
        else:
            return OCPIResponse(errors=serializer.errors)


class SessionViewSet(mixins.ListModelMixin,
                     GenericViewSet):
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['country_code', 'party_id', 'status', 'meter_id', 'cdr_token_uid', 'authorization_reference']
    pagination_class = OCPIPaginationAndHeaders
    lookup_field = 'uid'
    # noinspection PyUnresolvedReferences
    queryset = Session.objects.all().order_by('created')
    serializer_class = SessionSaveSerializer

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Session {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Sessions'

    @staticmethod
    def get_object(uid=None):
        # Needed for OPTIONS to work in list view, could just return None
        if uid:
            return get_object_or_404(Session, uid=uid)

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
        # ic(data)
        uid = data.get('uid')
        country_code = data.get('country_code')
        party_id = data.get('party_id')

        session: Session = Session.get_if_exists(uid=uid, party_id=party_id, country_code=country_code)
        if session:
            if not session.is_owner(request):
                return NotOwner()
            if session.is_final():
                return OCPIResponse('Cannot update a completed Session.', http_status=status.HTTP_403_FORBIDDEN,
                                    status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)
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
            "OpenAPI": request.build_absolute_uri(reverse('openapi-schema')),
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
