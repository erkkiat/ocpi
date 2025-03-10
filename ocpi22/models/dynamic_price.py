from django.db import models

from ocpi22.choices import DYNAMIC_PRICE_SOURCE_CHOICES


class DynamicPrice(models.Model):
    dynamic_price_source = models.CharField(
        max_length=10, null=True, blank=True, choices=DYNAMIC_PRICE_SOURCE_CHOICES
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    price = models.FloatField()
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)
