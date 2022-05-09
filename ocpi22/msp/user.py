from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework import viewsets
from rest_framework.decorators import action

from ocpi22.ocpi.util import OCPIResponse


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'password')

    username = serializers.EmailField(
        help_text="The user's email address"
    )
    password = serializers.CharField(
        required=False, write_only=True,
        help_text="The password to be set for this user"
    )

    def create(self, validated_data):
        raw_password = validated_data.pop('password', None)
        user: User = User(email=validated_data.get('username'), **validated_data)
        user.set_password(raw_password)
        user.save()
        return user


class UserViewSet(viewsets.GenericViewSet):
    lookup_field = 'username'
    queryset = User.objects.none()

    def get_serializer_class(self):
        return dict(
            add=UserSerializer,
        ).get(self.action_map.get('post'), UserSerializer)

    def get(self):
        return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')

    @action(methods=['POST', 'GET'], detail=False, url_path='create', name='Create')
    def add(self, request):
        if request.method == 'GET':
            return OCPIResponse(status_message='Please see OPTIONS to learn what you can POST at this endpoint')

        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return OCPIResponse(serializer.data)
        else:
            return OCPIResponse(errors=serializer.errors)
