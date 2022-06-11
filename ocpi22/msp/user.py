from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from rest_framework import serializers, status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.reverse import reverse

from cars.cars import get_models
from ocpi22.models.cdr import Cdr
from ocpi22.msp.account import Transaction, Account
from ocpi22.msp.models import PHONE_FIELD_LENGTH, VEHICLE_FIELD_LENGTH
from ocpi22.ocpi.serializers import CdrSerializer
from ocpi22.util import hours_minutes, HyperlinkedModelSerializerCleanedUp, StandardResultsSetPagination

options_response = Response(dict(status_message=f'Please see OPTIONS to learn what you can POST at this endpoint'))


class Username(serializers.CharField):
    def to_internal_value(self, data):
        user = User.objects.get(username=data)
        return user


# class CheckPasswordSerializer(serializers.Serializer):
#     username = Username(
#         help_text="The user's email address"
#     )
#     password = serializers.CharField(
#         write_only=True,
#         help_text="The password the user typed"
#     )


class ChangePasswordSerializer(serializers.Serializer):
    password = serializers.CharField(
        write_only=True, max_length=128,
        help_text="The password to be set for this user"
    )

    confirm = serializers.CharField(
        write_only=True, max_length=128,
        help_text="The same password again, straight from the user interface"
    )

    def update(self, user, validated_data):
        raw_password = validated_data.get('password')
        confirm_password = validated_data.get('confirm')
        if raw_password != confirm_password:
            raise ValidationError(dict(status_message=_("Password and confirm differ from each other")))
        if raw_password:
            user.set_password(raw_password)
            user.save()
        else:
            raise ValidationError(dict(
                status_message='Please POST or PATCH {"password": "newpassword", "confirm": "newpassword"}')
            )
        return user


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('email', 'firstname', 'lastname', 'telephone', 'vehicle')

    email = serializers.EmailField(read_only=True)
    firstname = serializers.CharField(source='first_name', required=False, allow_blank=True)
    lastname = serializers.CharField(source='last_name', required=False, allow_blank=True)

    telephone = serializers.CharField(source="profile.phone", max_length=PHONE_FIELD_LENGTH,
                                      required=False, allow_blank=True)
    vehicle = serializers.CharField(source="profile.vehicle", max_length=VEHICLE_FIELD_LENGTH,
                                    required=False, allow_blank=True)

    def update(self, user, validated_data):
        profile_data = validated_data.pop('profile', None)

        for key, value in validated_data.items():
            setattr(user, key, value)
        user.save()

        if profile_data:
            profile = user.profile
            for key, value in profile_data.items():
                setattr(profile, key, value)
            profile.save()

        return user

    def validate(self, attrs):
        car_model = attrs.get('profile', {}).get('vehicle')
        if car_model and not car_model in get_models():
            raise ValidationError(_("Car model {car_id} not found from database").format(car_id=car_model))
        return attrs


class RegistrationSerializer(ProfileSerializer):
    class Meta:
        model = User
        fields = ('email', 'firstname', 'lastname', 'telephone', 'vehicle', 'password', 'confirm')

    email = serializers.EmailField(
        help_text="The user's email address"
    )

    firstname = serializers.CharField(source='first_name', required=False, allow_blank=True)
    lastname = serializers.CharField(source='last_name', required=False, allow_blank=True)

    password = serializers.CharField(
        write_only=True, max_length=128,
        help_text="The password to be set for this user"
    )

    confirm = serializers.CharField(
        write_only=True, max_length=128,
        help_text="The same password again, straight from the user interface"
    )

    telephone = serializers.CharField(source="profile.phone", max_length=PHONE_FIELD_LENGTH,
                                      required=False, allow_blank=True)
    vehicle = serializers.CharField(source="profile.vehicle", max_length=VEHICLE_FIELD_LENGTH,
                                    required=False, allow_blank=True)

    def validate(self, attrs):
        car_model = attrs.get('profile', {}).get('vehicle')
        if car_model and not car_model in get_models():
            raise ValidationError(_("Car model {car_id} not found from database").format(car_id=car_model))
        return attrs

    def create(self, validated_data):
        raw_password = validated_data.pop('password', '')
        confirm_password = validated_data.pop('confirm', '')
        profile_data = validated_data.pop('profile', None)
        email = validated_data['email']

        if raw_password != confirm_password:
            raise ValidationError(dict(status_message=_("Password and confirm differ from each other")))

        user: User = User(username=email, **validated_data)
        user.set_password(raw_password)
        user.save()

        # Profile is created automatically for each User, so we need to just update it
        if profile_data:
            profile = user.profile
            for key, value in profile_data.items():
                setattr(profile, key, value)
            profile.save()

        return user


class TransactionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Transaction
        fields = ('delta', 'balance_after', 'discount', 'cdr', 'datetime')

    cdr = CdrSerializer()
    datetime = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")


class BriefCdrSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Cdr
        fields = ('location', 'token_id', 'authorization_reference', 'duration', 'total_time', 'detail_url')

    location = serializers.SerializerMethodField()
    token_id = serializers.CharField(source='cdr_token_uid')
    duration = serializers.SerializerMethodField()

    def get_location(self, instance: Cdr) -> dict:
        return dict(
            name=instance.cdr_location_name,
            address=f'{instance.cdr_location_address}, {instance.cdr_location_city}, {instance.cdr_location_country}',
            evse_id=instance.cdr_location_evse_id,
            connector_id=instance.cdr_location_connector_id,
            standard=instance.get_cdr_location_connector_standard_display(),
        )

    def get_duration(self, instance: Cdr) -> str:
        return hours_minutes(instance.total_time)


class BriefTransactionSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Transaction
        fields = ('delta', 'balance_after', 'currency', 'discount', 'total_energy', 'cdr',
                  'datetime', 'display_date', 'display_time')

    cdr = BriefCdrSerializer()
    datetime = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%SZ")
    display_date = serializers.DateTimeField(source='datetime', format="%-d.%-m.%Y")
    display_time = serializers.DateTimeField(source='datetime', format="%H:%M")
    total_energy = serializers.SerializerMethodField()
    currency = serializers.CharField(source='account.currency')

    def get_total_energy(self, obj) -> Decimal:
        if obj.cdr:
            return Decimal(obj.cdr.total_energy)
        return Decimal(0.0)


class UserViewSet(viewsets.GenericViewSet):
    publicly_visible = True
    queryset = User.objects.none()
    pagination_class = StandardResultsSetPagination
    paginator = pagination_class()

    def get_serializer_class(self):
        return dict(
            register=RegistrationSerializer,
            account=ProfileSerializer,
            password=ChangePasswordSerializer,
            transaction_list_brief=BriefTransactionSerializer,
            transaction_list_full=TransactionSerializer
        ).get(self.action_map['get'])

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'User {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Users'

    @action(methods=['POST', 'GET'], detail=False)
    def register(self, request):
        """
        This endpoint is open to all, since the user can only log in after registering
        """
        if request.method == 'GET':
            return options_response

        # POST
        try:
            serializer = RegistrationSerializer(data=request.data)
            if serializer.is_valid():
                user = serializer.save()
                Account.objects.create(customer=user)
                data = serializer.data.copy()
                data.pop('password', None)
                data.pop('confirm', None)
                return Response(data=data, status=status.HTTP_201_CREATED)
            else:
                return Response(serializer.errors)
        except IntegrityError as e:
            return Response(_('The user {email} already exists').format(
                email=serializer.validated_data.get("email")),
                status.HTTP_409_CONFLICT)

    @method_decorator(login_required)
    @action(methods=['GET', 'PATCH', 'POST'], detail=False)
    def account(self, request):
        user = request.user
        if request.method == 'GET':
            serializer = ProfileSerializer(instance=user)
            return Response(serializer.data)
        if request.method in ('POST', 'PATCH'):
            partial = bool(request.method == 'PATCH')
            serializer = ProfileSerializer(data=request.data, instance=user, partial=partial)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        return options_response

    @method_decorator(login_required)
    @action(methods=['GET', 'POST', 'PATCH'], detail=False)
    def password(self, request):
        user: User = request.user
        if request.method == 'GET':
            return options_response
        if request.method in ('POST', 'PATCH'):
            partial = bool(request.method == 'PATCH')
            serializer = ChangePasswordSerializer(data=request.data, instance=user, partial=partial)
            if serializer.is_valid():
                serializer.save()
                return Response(dict(status_message=_('Password has been changed successfully')))
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        return options_response

    def _build_transaction_list_urls(self, request) -> dict:
        transactions = Transaction.objects.all()
        if transactions.exists():
            user = transactions.last().account.customer
        else:
            user = User.objects.all().last()
        example1 = request.build_absolute_uri(
            "{}?{}".format(reverse('user-transaction-list-brief', kwargs=dict(username=user.username)), 'page_size=10')
        )
        example2 = request.build_absolute_uri(
            "{}?{}".format(reverse('user-transaction-list-full', kwargs=dict(username=user.username)), 'page_size=5')
        )
        return dict(
            example_brief_transaction_list=example1,
            example_full_transaction_list=example2
        )

    def _transaction_list(self, request, serializer, user=None):
        """
        Helper method for different types of Transaction lists
        """
        user = user or request.user
        account = user.accounts.all().first()
        transactions = self.paginator.paginate_queryset(
            account.transactions.all().order_by('-datetime') if account else Transaction.objects.none(), request
        )
        serializer = serializer(instance=transactions, many=True)
        return self.paginator.get_paginated_response(serializer.data)

    @method_decorator(login_required)
    @action(methods=['GET'], detail=False, url_path='transactions/brief')
    def transaction_list_brief(self, request):
        """
        This condensed information is ready to be displayed to the app user
        """
        return self._transaction_list(request, BriefTransactionSerializer)

    @method_decorator(login_required)
    @action(methods=['GET'], detail=False, url_path='transactions/full')
    def transaction_list_full(self, request):
        """
        This is the full data of the transactions for the authenticated user
        """
        return self._transaction_list(request, TransactionSerializer)

    @method_decorator(login_required)
    @action(methods=['GET'], detail=False)
    def car_details(self, request):
        car_id = request.user.profile.vehicle
        car = get_models().get(car_id)
        if not car:
            return Response(dict(status_message=_(f'Car model {car_id} not found from database')),
                            status=status.HTTP_404_NOT_FOUND)
        return Response(car.original_json)


class CdrViewSet(viewsets.GenericViewSet, viewsets.mixins.ListModelMixin, viewsets.mixins.RetrieveModelMixin):
    """
    This is the list of Charge Detail Records, which is used by the CPO for billing an MSP for charging sessions.
    You can use it for verifying the bill from the CPO.
    """

    # Todo: Limit access based on privileges set by admin

    model = Cdr
    queryset = Cdr.objects.all()
    lookup_field = 'uid'
    serializer_class = CdrSerializer
    pagination_class = StandardResultsSetPagination
