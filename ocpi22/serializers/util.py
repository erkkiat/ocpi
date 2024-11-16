from datetime import datetime
from typing import Union

from dateutil import parser
from dateutil.tz import tzoffset
from django.conf import settings
from rest_framework import serializers

from ocpi22.util import clear_empty, set_callbacks_parameter, build_absolute_uri


class SerializerCleanedUp(serializers.Serializer):
    def to_representation(self, instance):
        """Remove empty values"""
        repr_dict = super().to_representation(instance)
        result = clear_empty(repr_dict)
        return result


class HyperlinkedModelSerializerCleanedUp(serializers.HyperlinkedModelSerializer):
    def to_representation(self, value):
        # Remove empty values
        repr_dict = super().to_representation(value)
        result = clear_empty(repr_dict)
        return result

    def is_browser(self):
        request = self.context.get("request")
        if request and hasattr(request, "accepted_media_type"):
            return bool("text/html" in request.accepted_media_type)

    def get_detail_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        if (
            not hasattr(obj, "get_absolute_url")
            or not self.is_browser()
            or self.context.get("exclude_urls")
        ):
            return ""
        version = self.context.get("version")
        return f"{build_absolute_uri(obj.get_absolute_url(version))}"

    def get_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        if not hasattr(obj, "get_cpo_url") or not self.is_browser():
            return ""
        return f"{build_absolute_uri(obj.get_cpo_url())}"

    def get_quick_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        if not hasattr(obj, "get_quick_url") or not self.is_browser():
            return ""
        return f"{build_absolute_uri(obj.get_quick_url())}"

    def get_status_url(self, obj) -> str:
        """
        Construct a URL which points to the object instance view
        :param obj: The object we need the instance view for
        :return: The URL string to the instance view
        """
        if not hasattr(obj, "get_status_url") or not self.is_browser():
            return ""
        url = obj.get_status_url()
        if url:
            return f"{build_absolute_uri(url)}"

    detail_url = serializers.SerializerMethodField(
        read_only=True, help_text="This non-OCPI field exists for educational purposes"
    )
    url = serializers.SerializerMethodField(read_only=True)
    quick_url = serializers.SerializerMethodField(
        read_only=True, help_text="This non-OCPI field exists for educational purposes"
    )
    status_url = serializers.SerializerMethodField(
        read_only=True, help_text="This non-OCPI field exists for educational purposes"
    )


class CallbacksSerializer(serializers.Serializer):
    def save(self):
        for key, value in self.validated_data.items():
            set_callbacks_parameter(key, value)
        # redis_store.save()  # This is not allowed in Heroku Redis

    OutboundSerializer = None
    ResponseSerializer = None


class UTCDateTimeField(serializers.DateTimeField):
    def to_representation(self, value) -> str:
        assert isinstance(
            value, datetime
        ), f"Expected a datetime, got type {type(value)} with value {value}"
        value = value.astimezone(tzoffset(None, 0))
        result = value.strftime(settings.OCPI_DATE_FORMAT)
        return super().to_representation(result)

    def to_internal_value(self, value: Union[str, datetime]):
        if isinstance(value, datetime):
            return value
        assert isinstance(
            value, str
        ), f"Expected a string, got type {type(value)} with value {value}"
        value: datetime = parser.parse(value)
        if value and isinstance(value.tzinfo, tzoffset):
            raise serializers.ValidationError(
                "according to OCPI specification, datetimes should be in UTC timezone",
                code="invalid",
            )
        return value
