# Python unit tests for the models of the OCPI 2.2.1 implementation
from datetime import timezone, datetime

from django.test import TestCase
from ocpi22.models.hours import Hours, RegularHours, ExceptionalPeriod


class HoursModelTest(TestCase):
    def test_hours_str_basic(self):
        hours = Hours.objects.create(twentyfourseven=True)
        self.assertEqual(hours.get_hours_display_english(), "24/7")

        hours = Hours.objects.create(twentyfourseven=False)
        self.assertEqual(hours.get_hours_display_english(), "No regular hours")

    def test_hours_str_advanced(self):
        hours = Hours.objects.create(twentyfourseven=False)
        regular_hours = [
            RegularHours.objects.create(weekday=wd, period_begin="08:00", period_end="17:00")
            for wd in range(1, 6)
        ]
        regular_hours += [
            RegularHours.objects.create(weekday=wd, period_begin="10:00", period_end="18:00")
            for wd in range(6, 8)
        ]
        hours.regular_hours.set(regular_hours)
        self.assertEqual(hours.get_hours_display_english(), "No regular hours")

    def test_regular_hours_str(self):
        regular_hours = RegularHours.objects.create(weekday=1, period_begin="08:00", period_end="17:00")
        self.assertEqual(str(regular_hours), "Monday: 08:00 - 17:00")

    def test_exceptional_period_str(self):
        period_begin = datetime(2021, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2021, 1, 2, 18, 0, 0, tzinfo=timezone.utc)
        exceptional_period = ExceptionalPeriod.objects.create(period_begin=period_begin, period_end=period_end)
        self.assertEqual(str(exceptional_period), "January 1st 8:00 - January 2nd 18:00")
