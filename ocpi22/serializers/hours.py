from rest_framework import serializers
from ocpi22.models.hours import (
    RegularHours,
    ExceptionalOpening,
    Hours,
    ExceptionalClosing,
)
from ocpi22.serializers.util import UTCDateTimeField


class CustomTimeField(serializers.TimeField):
    def to_representation(self, value):
        # Format the time to HH:MM
        if value is None:
            return value
        if isinstance(value, str):
            # check that the format matches HH:MM
            if len(value) == 5 and value[2] == ":":
                return value
            raise ValueError("Time has to be in HH:MM format")
        return value.strftime("%H:%M")


class RegularHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegularHours
        fields = ["weekday", "period_begin", "period_end"]

    period_begin = CustomTimeField()
    period_end = CustomTimeField()


class ExceptionalPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExceptionalOpening
        fields = ["period_begin", "period_end"]

    period_begin = UTCDateTimeField()
    period_end = UTCDateTimeField()


class HoursSerializer(serializers.ModelSerializer):
    regular_hours = RegularHoursSerializer(many=True, required=False)
    exceptional_openings = ExceptionalPeriodSerializer(many=True, required=False)
    exceptional_closings = ExceptionalPeriodSerializer(many=True, required=False)

    class Meta:
        model = Hours
        fields = [
            "regular_hours",
            "twentyfourseven",
            "exceptional_openings",
            "exceptional_closings",
        ]

    def create(self, validated_data, location=None):
        regular_hours_data = validated_data.pop("regular_hours", [])
        exceptional_openings_data = validated_data.pop("exceptional_openings", [])
        exceptional_closings_data = validated_data.pop("exceptional_closings", [])
        hours_instance = Hours.objects.create(location=location, **validated_data)

        for rh_data in regular_hours_data:
            RegularHours.objects.create(hours=hours_instance, **rh_data)

        for eo_data in exceptional_openings_data:
            ExceptionalOpening.objects.create(hours=hours_instance, **eo_data)

        for ec_data in exceptional_closings_data:
            ExceptionalClosing.objects.create(hours=hours_instance, **ec_data)

        return hours_instance

    def update(self, instance, validated_data):
        regular_hours_data = validated_data.pop("regular_hours", [])
        exceptional_openings_data = validated_data.pop("exceptional_openings", [])
        exceptional_closings_data = validated_data.pop("exceptional_closings", [])

        instance.twentyfourseven = validated_data.get(
            "twentyfourseven", instance.twentyfourseven
        )
        instance.save()

        instance.regular_hours.all().delete()
        for rh_data in regular_hours_data:
            RegularHours.objects.create(hours=instance, **rh_data)

        instance.exceptional_openings.all().delete()
        for eo_data in exceptional_openings_data:
            ExceptionalOpening.objects.create(hours=instance, **eo_data)

        instance.exceptional_closings.all().delete()
        for ec_data in exceptional_closings_data:
            ExceptionalClosing.objects.create(hours=instance, **ec_data)

        return instance
