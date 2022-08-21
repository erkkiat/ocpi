from rest_framework import serializers

from ocpi22.util import clear_empty, set_callbacks_parameter


class SerializerCleanedUp(serializers.Serializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        result = clear_empty(repr_dict)
        return result


class HyperlinkedModelSerializerCleanedUp(serializers.HyperlinkedModelSerializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        result = clear_empty(repr_dict)
        return result

    def get_detail_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_absolute_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_absolute_url())}'

    def get_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_cpo_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_cpo_url())}'

    def get_quick_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_quick_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_quick_url())}'

    def get_status_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        request = self.context.get("request")
        if not hasattr(obj, 'get_status_url') or not request:
            return ''
        return f'{request.build_absolute_uri(obj.get_status_url())}'

    detail_url = serializers.SerializerMethodField(
        read_only=True,
        help_text='This non-OCPI field exists for educational purposes'
    )
    url = serializers.SerializerMethodField(read_only=True)
    quick_url = serializers.SerializerMethodField(
        read_only=True,
        help_text='This non-OCPI field exists for educational purposes'
    )
    status_url = serializers.SerializerMethodField(
        read_only=True,
        help_text='This non-OCPI field exists for educational purposes'
    )


class CallbacksSerializer(serializers.Serializer):
    def save(self):
        for key, value in self.validated_data.items():
            set_callbacks_parameter(key, value)
        # redis_store.save()  # This is not allowed in Heroku Redis
