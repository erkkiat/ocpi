from django.db import models
from django.utils import dateformat
from django.utils.translation import gettext_lazy as _

# Todo: What does the client need, Hours.is_open_now(), Hours.how_long_until_open(), Hours.how_long_until_close()?


class RegularHours(models.Model):
    WEEKDAY_CHOICES = [
        (1, 'Monday'),
        (2, 'Tuesday'),
        (3, 'Wednesday'),
        (4, 'Thursday'),
        (5, 'Friday'),
        (6, 'Saturday'),
        (7, 'Sunday'),
    ]

    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    period_begin = models.TimeField()
    period_end = models.TimeField()

    def __str__(self):
        return f"{self.get_weekday_display()}: {self.period_begin}-{self.period_end}"

    class Meta:
        verbose_name = _("Regular Hours")
        verbose_name_plural = _("Regular Hours")


class ExceptionalPeriod(models.Model):
    period_begin = models.DateTimeField()
    period_end = models.DateTimeField()

    def __str__(self):
        # Format period_begin and period_end using Django's dateformat utility
        begin_formatted = dateformat.format(self.period_begin, 'F jS G:i')
        end_formatted = dateformat.format(self.period_end, 'F jS G:i')
        return f"{begin_formatted} - {end_formatted}"

    class Meta:
        verbose_name = _("Exceptional Period")
        verbose_name_plural = _("Exceptional Periods")


class Hours(models.Model):
    regular_hours = models.ManyToManyField("ocpi22.RegularHours", blank=True)
    twentyfourseven = models.BooleanField()
    exceptional_openings = models.ManyToManyField("ocpi22.ExceptionalPeriod", related_name='exceptional_openings',
                                                  blank=True)
    exceptional_closings = models.ManyToManyField("ocpi22.ExceptionalPeriod", related_name='exceptional_closings',
                                                  blank=True)

    def __str__(self):
        return _(self.get_hours_display_english())

    def get_hours_display_english(self):
        if self.twentyfourseven:
            return "24/7"

        regular_hours = self.regular_hours.all().order_by('weekday', 'period_begin')
        if not regular_hours:
            return "No regular hours"

        grouped_hours = {}
        for rh in regular_hours:
            key = (rh.period_begin, rh.period_end)
            if key not in grouped_hours:
                grouped_hours[key] = []
            grouped_hours[key].append(rh.weekday)

        parts = []
        for (begin, end), weekdays in grouped_hours.items():
            if len(weekdays) > 1:
                part = f"{_(RegularHours.WEEKDAY_CHOICES[weekdays[0] - 1][1])[:3]}-{_(RegularHours.WEEKDAY_CHOICES[weekdays[-1] - 1][1])[:3]} {begin.strftime('%H')} - {end.strftime('%H')}"
            else:
                part = f"{_(RegularHours.WEEKDAY_CHOICES[weekdays[0] - 1][1])[:3]} {begin.strftime('%H')} - {end.strftime('%H')}"
            parts.append(part)

        return ", ".join(parts)

    class Meta:
        verbose_name = _("Hours")
        verbose_name_plural = _("Hours")
