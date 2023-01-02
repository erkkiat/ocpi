import doctest
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import geopy
import time_machine
from django.test import TestCase

from django.contrib.auth.models import AnonymousUser
from rest_framework import status
from rest_framework.exceptions import ErrorDetail

from util import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.cpo import test_data
from ocpi22.cpo.api import LocationQuickViewSet
from ocpi22.cpo.serializers import LocationQuickSerializer
from ocpi22.cpo.tariff import TariffQuickViewSet
from ocpi22.models.location import Location
from ocpi22.models.session import Session
from ocpi22.tests import meter_values

api_factory = APIRequestFactory()


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.cpo.util'))
    return tests


class TestQuickLocations(TestCase):
    fixtures = ['ocpi22/cpo/database-dumps/tariffs.json']
    maxDiff = 99999

    def test_quick_location(self):
        #
        # Test new location outside of any cities, coordinates as string
        #

        data = {
            "id": "Aplinkkelis",
            "name": "IONITY High Power Charging Aplinkkelis",
            "latitude": "55.67309",
            "longitude": "24.33591"
        }
        try:
            response = put_location(data, reverse('quick-location-list'))
            self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                             'Expecting Location to be created successfully')
            location = Location.get_if_exists(uid='Aplinkkelis')
            data = LocationQuickSerializer(instance=location).data
            self.assertEqual(data,
                             {
                                 # 'quick_url': 'http://testserver.test/api/cpo/v2/location/quick/APLINKKELIS/',
                                 'id': 'APLINKKELIS', 'name': 'IONITY High Power Charging Aplinkkelis',
                                 'address': 'Panevėžio aplinkl. 20', 'city': '-', 'postal_code': '38417',
                                 'country': 'LTU',
                                 'time_zone': 'Europe/Vilnius', 'latitude': 55.67309, 'longitude': 24.33591
                             },
                             f'New Location data differs from expected: {data}')
        except geopy.exc.GeocoderUnavailable:
            self.skipTest('Geocoder is unavailable')

        #
        # Try updating Location data with new coordinates, address should be updated automatically
        #

        data = {
            "id": "Aplinkkelis",
            "latitude": 42.6975216,
            "longitude": 23.3191493
        }
        response = patch_location(data, reverse('quick-location-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         'Expecting Location to be updated successfully')
        location = Location.get_if_exists(uid='Aplinkkelis')
        data = LocationQuickSerializer(instance=location).data
        self.assertEqual(data,
                         # Todo: Maybe we should have English addresses available in parallel?
                         {
                             # 'quick_url': 'http://testserver.test/api/cpo/v2/location/quick/Aplinkkelis/',
                             'id': 'Aplinkkelis', 'name': 'IONITY High Power Charging Aplinkkelis',
                             'address': 'Княз Борис Ⅰ 134', 'city': 'София', 'postal_code': '1000', 'country': 'BGR',
                             'time_zone': 'Europe/Sofia', 'latitude': 42.6975216, 'longitude': 23.3191493
                         },
                         'Updated Location data differs from expected')

    def test_quick_location_with_evses_and_connectors(self):
        #
        # Create Location
        #

        response = put_location(test_data.LocationData.location1, reverse('quick-location-list'))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         'Expecting Location to be created successfully')
        location = Location.get_if_exists(uid=test_data.LocationData.location1.get('id'))
        data = LocationQuickSerializer(instance=location).data
        expected_data = {
            # 'quick_url': 'http://testserver.test/api/cpo/v2/location/quick/EKI1/',
            'id': 'EKI1', 'name': "Eki's home charger", 'address': 'Kotikatu 38', 'city': 'Espoo',
            'postal_code': '01234', 'country': 'FIN', 'time_zone': 'Europe/Helsinki', 'latitude': 60.0,
            'longitude': 30.0, 'evses': [dict([('uid', '1'), ('connectors', [dict(
                [('uid', '1'), ('standard', 'IEC_62196_T2'), ('format', 'CABLE'), ('max_voltage', 233),
                 ('max_amperage', 32), ('max_electric_power', 22200), ('tariff_ids', ['EKI1'])])])]),
                                         dict([('uid', '2'), ('connectors', [dict(
                                             [('uid', '1'), ('standard', 'IEC_62196_T2'),
                                              ('format', 'SOCKET'), ('max_voltage', 232),
                                              ('max_amperage', 32)])])]),
                                         dict([('uid', 'JAAU254040-1'), ('connectors', [
                                             dict([('uid', '1'), ('standard', 'IEC_62196_T2'),
                                                   ('format', 'CABLE'), ('max_voltage', 233),
                                                   ('max_amperage', 32),
                                                   ('tariff_ids', ['DC50'])])])])]
        }
        self.assertEqual(data, expected_data, 'New Location data differs from expected')

        #
        # Update Location
        #

        response = patch_location(test_data.LocationData.location_update1, reverse('quick-location-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         'Expecting Location to be updated successfully')
        location = Location.get_if_exists(uid=test_data.LocationData.location_update1.get('id'))
        data = LocationQuickSerializer(instance=location).data
        expected_data = {
            'id': 'EKI1', 'name': "Eki's home charger", 'address': 'Kotikatu 38', 'city': 'Espoo',
            'postal_code': '01234', 'country': 'FIN', 'time_zone': 'Europe/Helsinki', 'latitude': 60.0,
            'longitude': 30.0,  # 'quick_url': 'http://testserver.test/api/cpo/v2/location/quick/EKI1/',
            'evses':
                [
                    OrderedDict([('uid', '1'),
                                 ('connectors', [OrderedDict(
                                     [('uid', '1'), ('standard', 'IEC_62196_T2'), ('format', 'SOCKET'),
                                      ('max_voltage', 233),
                                      ('max_amperage', 32), ('max_electric_power', 11000),
                                      ('tariff_ids', ['DC50'])])]),
                                 ('last_updated', '2022-06-19T12:13:14')]),
                    OrderedDict(
                        [('uid', '2'), ('connectors', [OrderedDict(
                            [('uid', '1'), ('standard', 'IEC_62196_T2'), ('format', 'SOCKET'), ('max_voltage', 232),
                             ('max_amperage', 32)])])]),
                    OrderedDict([('uid', 'JAAU254040-1'), ('connectors', [OrderedDict(
                        [('uid', '1'), ('standard', 'IEC_62196_T2'), ('format', 'CABLE'), ('max_voltage', 233),
                         ('max_amperage', 32), ('tariff_ids', ['DC50'])])])])
                ]
        }
        self.assertEqual(data, expected_data, 'Updated Location data differs from expected')

    def test_quick_tariff(self):
        test_cases = [
            dict(
                data={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 1.0,
                    "price_per_min": 2.0,
                    "price_flat": 3.0,
                    "vat": 24.0
                },
                status=status.HTTP_201_CREATED
            ),
            dict(
                data={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 1.0,
                    "price_per_min": 2.0,
                    "price_flat": 3.0,
                    "vat": 0.24
                },
                status=status.HTTP_400_BAD_REQUEST,
                expected_result={
                    'vat': [ErrorDetail(string='VAT needs to be an integer value between 0 and 100', code='invalid')]
                }
            ),
            dict(
                method='PATCH',
                data={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 3.0,
                    "price_per_min": 2.0,
                },
                status=status.HTTP_200_OK,
                expected_result={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 3.0,
                    "price_per_min": 2.0,
                    "price_flat": 3.0,
                    "vat": 24
                }
            ),
            dict(
                method='PATCH',
                data={
                    "id": "ALLTYPES",
                    "price_per_kwh": 0.0,
                    "vat": 0,
                },
                status=status.HTTP_200_OK,
                expected_result={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 0.0,
                    "price_per_min": 2.0,
                    "price_flat": 3.0,
                    "vat": 0
                }
            ),
            dict(
                method='PATCH',
                data={
                    "id": "ALLTYPES",
                    "price_per_kwh": 0.0,
                    "vat": None,
                },
                status=status.HTTP_200_OK,
                expected_result={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 0.0,
                    "price_per_min": 2.0,
                    "price_flat": 3.0,
                    "vat": 0
                }
            ),
        ]
        for case in test_cases:
            data = case['data']
            if case.get('method') == 'PATCH':
                response = send_patch(data, reverse('quick-tariff-list'), TariffQuickViewSet)
            else:
                response = put(data, reverse('quick-tariff-list'), TariffQuickViewSet)
            self.assertEqual(response.status_code, case.get('status', status.HTTP_200_OK),
                             'Quick Tariff creation/update response status differs from expected')
            self.assertDictEqual(response.data, case.get('expected_result', data),
                                 'Quick Tariff creation/update response data differs from expected')

        # The below needs some work
        # response = get(reverse('quick-tariff-list'), TariffQuickViewSet)
        # ic(response.status_code, response.data)


class TestChargingPeriods(TestCase):
    fixtures = [
        'ocpi22/cpo/database-dumps/complex-tariffs-1.json',
        'ocpi22/cpo/database-dumps/tariffs-time-weekday.json'
    ]
    maxDiff = None

    def test_tariff_change(self):
        meter_values_data = (
            # (kWh, SoC, timestamp)
            (2, 52, datetime(2022, 12, 25, 23, 55),  # Weekday 6 = Sunday
             {  # Check send_update() parameters for the first call
                 'kwh': Decimal('2.000'),
                 'last_updated': '2022-12-25T23:55:00Z',
                 'total_cost': {'excl_vat': 0.6, 'incl_vat': 0.74},
                 'charging_periods': [
                     OrderedDict([('start_date_time', '2022-12-25T23:55:00Z'), (
                         'tariff', 'WEEKENDS'), ('dimensions',
                                                 [OrderedDict([('type', 'ENERGY'), ('volume', '2.0000')]),
                                                  OrderedDict([('type', 'STATE_OF_CHARGE'), (
                                                      'volume', '52.0000')])])])
                 ]
             }, {
                 'internal_reference': None,
                 'now_kwh': 2.0,
                 'power': None,
                 'price': '0,74zł',
                 'session_id': 'FI*000*S*B58DDC4D3B304A47AD623C22147',
                 'soc': 52.0,
                 'start_kwh': 0.0,
                 'status_text': 'Session updated',
                 'total_kwh': Decimal('2.000')
             }
             ),
            (7, 57, datetime(2022, 12, 25, 23, 58), None, None),
            (10, 60, datetime(2022, 12, 26, 00, 1), None, None),  # Weekday 0 = Monday
            (13, 63, datetime(2022, 12, 26, 00, 3), None, None),
            (15, 65, datetime(2022, 12, 26, 00, 5), None, None),
            (45, 95, datetime(2022, 12, 26, 8, 0), None, None),
            (45, 95, datetime(2022, 12, 26, 8, 0), None, None),
        )

        session_id = 'FI*000*S*B58DDC4D3B304A47AD623C22147'

        session = Session.get_if_exists(uid=session_id)
        self.assertEqual(
            session.connector.tariff_ids.all().first().price(),
            '0,50€/kWh (Weekdays 7-21), 0,40€/kWh (Weekdays 21-7)',
            'Price formatting works differently than expected'
        )

        for kwh, soc, timestamp, expected_args, expected_response in meter_values_data:
            try:
                with self.subTest(kwh=kwh, timestamp=timestamp):
                    with time_machine.travel(timestamp, tick=False), \
                            patch('ocpi22.ocpi.util.OcpiModule.send_updates') as send_updates, \
                            patch('ocpi22.util.is_our_identifier', return_value=True):

                        response = meter_values(dict(session_id=session_id, kwh=kwh, soc=soc, timestamp=timestamp))

                    self.assertEqual(response.status_code, 200,
                                     f'Unexpected response from meter_values(): {response.data}')
                    self.assertEqual(send_updates.call_count, 1, 'send_update() should have been called once')

                    args, kwargs = send_updates.call_args
                    if expected_args:
                        self.assertDictEqual(args[0], expected_args,
                                             f'send_update() got different parameters than expected: {args[0]}')

                    if expected_response:
                        self.assertDictEqual(response.data, expected_response,
                                             f'Response differs from expected: {response.data}')
            except AssertionError:
                ic(args[0], response.data)
                raise


def put(data, url, viewset):
    request = api_factory.put(url)
    request.data = data
    request.user = AnonymousUser
    return viewset().put(request)


def send_patch(data, url, viewset):
    request = api_factory.patch(url)
    request.data = data
    request.user = AnonymousUser
    return viewset().patch(request)


def get(url, viewset):
    request = api_factory.get(url, data={})
    request.user = AnonymousUser
    request.data = {}
    return viewset().list(request)


def put_location(data, url):
    request = api_factory.put(url)
    request.data = data
    request.user = AnonymousUser
    return LocationQuickViewSet().put(request)


def patch_location(data, url):
    request = api_factory.patch(url)
    request.data = data
    request.user = AnonymousUser
    return LocationQuickViewSet().patch(request)
