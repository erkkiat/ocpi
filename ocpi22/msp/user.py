from django.contrib.auth.models import User
from rest_framework import serializers, status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.reverse import reverse

from ocpi22.models.cdr import Cdr
from ocpi22.msp.account import Transaction
from ocpi22.ocpi.serializers import CdrSerializer
from ocpi22.util import hours_minutes, HyperlinkedModelSerializerCleanedUp, StandardResultsSetPagination

options_response = Response(dict(status_message=f'Please see OPTIONS to learn what you can POST at this endpoint'))


class Username(serializers.CharField):
    def to_internal_value(self, data):
        user = User.objects.get(username=data)
        return user


class CheckPasswordSerializer(serializers.Serializer):
    username = Username(
        help_text="The user's email address"
    )
    password = serializers.CharField(
        write_only=True,
        help_text="The password the user typed"
    )


class PatchUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'password', 'transactions')

    password = serializers.CharField(
        required=False, write_only=True,
        help_text="The password to be set for this user"
    )

    transactions = serializers.SerializerMethodField()

    def get_transactions(self, _instance: User) -> str:
        return self.context.get('transactions_url')

    def update(self, user, validated_data):
        validated_data.pop('username', None)
        raw_password = validated_data.pop('password', None)
        super().update(user, validated_data)
        if raw_password:
            user.set_password(raw_password)
            user.save()
        return user


class UserSerializer(PatchUserSerializer):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'password', 'detail_url')

    username = serializers.EmailField(
        help_text="The user's email address"
    )
    detail_url = serializers.SerializerMethodField()

    def get_detail_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        return request.build_absolute_uri(reverse('user-user-data', args=[obj.username]))

    def create(self, validated_data):
        raw_password = validated_data.pop('password', None)
        user: User = User(email=validated_data.get('username'), **validated_data)
        user.set_password(raw_password)
        user.save()
        return user


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        exclude = ['account']

    cdr = CdrSerializer()


class BriefCdrSerializer(HyperlinkedModelSerializerCleanedUp):
    class Meta:
        model = Cdr
        fields = ('location', 'token_id', 'authorization_reference', 'duration', 'detail_url')

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


class BriefTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        exclude = ['account', 'pos_reference']

    cdr = BriefCdrSerializer()


class UserViewSet(viewsets.GenericViewSet):
    lookup_field = 'username'
    queryset = User.objects.all()
    pagination_class = StandardResultsSetPagination
    paginator = pagination_class()

    def get_serializer_class(self):
        return dict(
            add=UserSerializer,
            user_data=PatchUserSerializer,
            check_password=CheckPasswordSerializer,
        ).get(self.action_map.get('get'), UserSerializer)

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'User {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Users'

    def list(self, request):
        serializer = UserSerializer(self.paginator.paginate_queryset(User.objects.all(), request),
                                    many=True, context={'request': request})
        return self.paginator.get_paginated_response(serializer.data)

    @action(methods=['POST', 'GET'], detail=False, url_path='create', name='Create')
    def add(self, request):
        if request.method == 'GET':
            return options_response

        # POST
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(dict(data=serializer.data,
                                 detail_url=request.build_absolute_uri(reverse("user-user-data", args=[user.username])))
                            )
        else:
            return Response(errors=serializer.errors)

    @action(methods=['GET', 'PATCH'], detail=False, url_path='(?P<username>[a-z0-9.@_]+)')
    def user_data(self, request, username=None, format=None):
        if not username:
            return options_response

        user = get_object_or_404(User, username=username)
        transactions_brief_url = request.build_absolute_uri(reverse('user-transaction-list-brief', args=[username]))
        if request.method == 'GET':
            serializer = PatchUserSerializer(instance=user, context=dict(transactions_url=transactions_brief_url))
        if request.method == 'PATCH':
            serializer = PatchUserSerializer(data=request.data, instance=user, partial=True)
            if serializer.is_valid():
                serializer.save()
        return Response(serializer.data, content_type=format)

    @action(methods=['POST', 'GET'], detail=False)
    def check_password(self, request):
        if request.method == 'GET':
            return options_response
        serializer = CheckPasswordSerializer(data=request.data)
        if serializer.is_valid():
            user: User = serializer.validated_data['username']
            password = serializer.validated_data['password']
            if (user.check_password(password)):
                return Response(dict(status_message='This password is valid for the user'))
            else:
                return Response(dict(status_message='This password is INVALID for the user'),
                                status=status.HTTP_401_UNAUTHORIZED)

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

    def _transaction_list(self, request, serializer, username=None):
        """
        Helper method for different types of Transaction lists
        """
        if not username:
            return Response(self._build_transaction_list_urls(request))
        user = get_object_or_404(User, username=username)
        account = user.accounts.all().first()
        transactions = self.paginator.paginate_queryset(
            account.transactions.all() if account else Transaction.objects.none(), request
        )
        serializer = serializer(instance=transactions, many=True)
        return self.paginator.get_paginated_response(serializer.data)

    @action(methods=['GET'], detail=False, url_path='transactions/brief(?:/(?P<username>[a-z0-9.@_+]+))?')
    def transaction_list_brief(self, request, username=None):
        """
        This condensed information is ready to be displayed to the app user
        """
        return self._transaction_list(request, BriefTransactionSerializer, username)

    @action(methods=['GET'], detail=False, url_path='transactions/full(?:/(?P<username>[a-z0-9.@_+]+))?')
    def transaction_list_full(self, request, username=None):
        """
        This is the full data of the transactions for the specified user
        """
        return self._transaction_list(request, TransactionSerializer, username)


class CdrViewSet(viewsets.GenericViewSet, viewsets.mixins.ListModelMixin, viewsets.mixins.RetrieveModelMixin):
    """
    This is the list of Charge Detail Records, which is used by the CPO for billing an MSP for charging sessions.
    You can use it for verifying the bill from the CPO.
    """
    model = Cdr
    queryset = Cdr.objects.all()
    lookup_field = 'uid'
    serializer_class = CdrSerializer
    pagination_class = StandardResultsSetPagination
