import logging
import os
from datetime import datetime, timedelta

import requests
from django.db import models
from requests import JSONDecodeError
from requests.auth import HTTPBasicAuth

DYNAMIC_PRICE_SOURCE_CHOICES = (
    ('IBEXBGIDM', 'IBEX.bg Intraday'),
    ('IBEXBGDAM', 'IBEX.bg Day ahead'),
    ('NPFI', 'Nordpool Finland'),
    ('NPEE', 'Nordpool Estonia'),
    ('NPLV', 'Nordpool Latvia'),
    ('NPLT', 'Nordpool Lithuania'),
    ('NPOslo', 'Nordpool Oslo'),
    ('NPBergen', 'Nordpool Bergen'),
    ('NPMolde', 'Nordpool Molde'),
    ('NPSE1', 'Nordpool Sweden 1'),
    ('NPSE2', 'Nordpool Sweden 2'),
    ('NPSE3', 'Nordpool Sweden 3'),
    ('NPSE4', 'Nordpool Sweden 4'),
    ('NPDK1', 'Nordpool Denmark 1'),
    ('NPDK2', 'Nordpool Denmark 2'),
    ('NPAT', 'Nordpool Austria'),
    ('NPBE', 'Nordpool Belgium'),
    ('NPFR', 'Nordpool France'),
    ('NPNL', 'Nordpool Netherlands'),
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
        def __init__(self, s='More than one price matched a single datetime'):
            super().__init__(s)

    key = None
    currency = 'EUR'

    def update(self):
        raise NotImplementedError()

    def _upsert_to_database(self, start: datetime, end: datetime, price: float):
        assert end > start
        dynamic_price, _created = DynamicPrice.objects.get_or_create(
            dynamic_price_source=self.key,
            start_datetime=start,
            end_datetime=end,
            defaults=dict(price=price)
        )
        print(str(dynamic_price))
        return dynamic_price


class IbexBgIdm(PriceSource):
    key = 'IBEXBGIDM'
    currency = "BGN"

    @staticmethod
    def _convert_date_format(d) -> datetime:
        """
        >>> IbexBgIdm._convert_date_format('220208-01:00')
        datetime.datetime(2022, 2, 8, 1, 0)
        >>> IbexBgIdm._convert_date_format('220131-24:00')  # Midnight on the next day
        datetime.datetime(2022, 2, 1, 0, 0)
        >>> IbexBgIdm._convert_date_format('120809-16:53')
        datetime.datetime(2012, 8, 9, 16, 53)
        """
        date, time = d.split('-')
        year, month, day = [int(i) for i in (d[0:2], d[2:4], d[4:6])]
        hour, minute = [int(i) for i in time.split(':')]
        if hour >= 24:
            return datetime(2000 + year, month, day, hour - 24, minute) + timedelta(days=1)
        return datetime(2000 + year, month, day, hour, minute)

    def update(self):
        try:
            credentials = os.environ.get('IBEX_CREDENTIALS', ':')
            user, password = credentials.split(':')
            response = requests.get(os.environ.get('IBEX_URL'), verify=False, auth=HTTPBasicAuth(user, password))
            prices = response.json()
            for p in prices:
                end_date = self._convert_date_format(p['Date/Hour'])
                start_date = end_date - timedelta(hours=1)
                price = float(p['Avg.price']) / 1000.0
                # print(p, start_date, end_date, price)
                self._upsert_to_database(start_date, end_date, price)
        except JSONDecodeError as e:
            raise requests.exceptions.ConnectionError('Missing IBEX_CREDENTIALS or JSON format error.')


class NordpoolFr(PriceSource):
    key = 'NPFR'
    currency = "EUR"

    def update(self):
        pass


class NordpoolFi(PriceSource):
    key = 'NPFI'
    currency = "EUR"

    def update(self):
        pass


class NordPool(PriceSource):
    key = ''
    currency = 'EUR'

    def update(self):
        from nordpool import elspot
        prices_spot = elspot.Prices()
        prices = prices_spot.hourly()
        for key, area in prices['areas'].items():
            source_name = f'NP{key}'
            print(source_name)
            for p in area['values']:
                value = None
                try:
                    value = p.get('value', 0.0)
                    if value == float('inf'):
                        value = 0.0
                    print(value, p['start'])
                    # noinspection PyUnresolvedReferences
                    DynamicPrice.objects.get_or_create(
                        dynamic_price_source=source_name,
                        start_datetime=p['start'].replace(tzinfo=None),
                        end_datetime=p['end'].replace(tzinfo=None),
                        defaults=dict(price=value)
                    )
                except KeyError:
                    logging.warning(f'Unable to set value {value} for {source_name} at {p["start"]}.')


dynamic_price_sources = (
    IbexBgIdm(),
    # NordPool(),
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
