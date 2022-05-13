from django.contrib.auth.models import User
from rest_framework import serializers, status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.reverse import reverse

from ocpi22.msp.account import Transaction
from ocpi22.ocpi.serializers import CdrSerializer

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
        fields = ('first_name', 'last_name', 'password')

    password = serializers.CharField(
        required=False, write_only=True,
        help_text="The password to be set for this user"
    )

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


class UserViewSet(viewsets.GenericViewSet):
    lookup_field = 'username'
    queryset = User.objects.all()

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
        serializer = UserSerializer(User.objects.all(), many=True, context={'request': request})
        return Response(serializer.data)

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
        if request.method == 'GET':
            serializer = PatchUserSerializer(instance=user)
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

    @action(methods=['GET'], detail=False, url_path='transactions/(?P<username>[a-z0-9.@_]+)?')
    def transaction_list(self, _request, username=None):
        if not username:
            return options_response
        user = get_object_or_404(User, username=username)
        account = user.accounts.all().first()
        if account:
            transactions = account.transactions.all()
            serializer = TransactionSerializer(instance=transactions, many=True)
            return Response(serializer.data)
        return Response([])
