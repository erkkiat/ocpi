from datetime import datetime

from django.db import models

DYNAMIC_PRICE_SOURCE_CHOICES = (
    ('IBEXBGIDM', 'IBEX.bg Intraday'),
    ('IBEXBGDAM', 'IBEX.bg Day ahead'),
)


class DynamicPrice(models.Model):
    dynamic_price_source = models.CharField(max_length=10, null=True, blank=True, choices=DYNAMIC_PRICE_SOURCE_CHOICES)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    price = models.FloatField()

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.get_dynamic_price_source_display()}: ' \
               f'{self.start_datetime} - {self.end_datetime} :: ' \
               f'{self.price}'


class PriceSource:
    class TooManyPrices(Exception):
        def __init__(self, str='More than one price matched a single datetime'):
            super().__init__(str)

    key = None
    currency = 'EUR'


class IbexBgIdm:
    key = 'IBEXBGIDM'
    currency = "BGN"


dynamic_price_sources = (
    IbexBgIdm(),
)


def get_price(key: str, when: datetime) -> float:
    """
    >>> DynamicPrice.objects.create(dynamic_price_source='ABC', price=1.0, start_datetime=datetime(2000,1,1,1,0), end_datetime=datetime(2000,1,1,2,0))
    <DynamicPrice: ABC: 2000-01-01 01:00:00 - 2000-01-01 02:00:00 :: 1.0>
    >>> DynamicPrice.objects.create(dynamic_price_source='ABC', price=2.0, start_datetime=datetime(2000,1,1,2,0), end_datetime=datetime(2000,1,1,3,0))
    <DynamicPrice: ABC: 2000-01-01 02:00:00 - 2000-01-01 03:00:00 :: 2.0>
    >>> get_price('ABC', datetime(2000,1,1,2,0))
    2.0

    @param key:
    @param when:
    @return:
    """
    # noinspection PyUnresolvedReferences
    prices = DynamicPrice.objects.filter(dynamic_price_source=key, start_datetime__lte=when, end_datetime__gt=when)
    if prices.count() == 0:
        return 0.0
    if prices.count() == 1:
        # return timezone.now().second/100
        return prices[0].price
    raise PriceSource.TooManyPrices()
