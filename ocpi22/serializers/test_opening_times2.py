from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from ocpi22.models.hours import RegularHours, ExceptionalPeriod
from ocpi22.models.test_opening_hours import create_advanced_hours_testdata
from ocpi22.serializers.hours import (
    RegularHoursSerializer,
    ExceptionalPeriodSerializer,
    HoursSerializer,
)
from ocpi22.serializers.test_data import HoursTest
from ocpiconnector.testutil import compare_dicts_recursively


class HoursModelTest(TestCase):
    def test_regular_hours_serialization(self):
        regular_hour = RegularHours.objects.create(
            weekday=1, period_begin="08:00", period_end="18:00"
        )
        serializer = RegularHoursSerializer(regular_hour)
        self.assertEqual(serializer.data, HoursTest.regular_hours)

    def test_exceptional_period_serialization(self):
        period_begin = datetime(2021, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        period_end = period_begin + timezone.timedelta(hours=2)
        exceptional_period = ExceptionalPeriod.objects.create(
            period_begin=period_begin, period_end=period_end
        )
        serializer = ExceptionalPeriodSerializer(exceptional_period)
        self.assertEqual(serializer.data, HoursTest.exceptional_period)

    def test_hours_serialization(self):
        hours = create_advanced_hours_testdata()
        serializer = HoursSerializer(hours)
        self.assertTrue(
            compare_dicts_recursively(serializer.data, HoursTest.advanced_hours)
        )
