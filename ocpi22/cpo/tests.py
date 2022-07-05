import doctest
from collections import OrderedDict

from django.test import TestCase

from django.contrib.auth.models import AnonymousUser
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.cpo import test_data
from ocpi22.cpo.api import LocationQuickViewSet
from ocpi22.cpo.serializers import LocationQuickSerializer
from ocpi22.models.location import Location

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
        response = put_location(data, reverse('quick-location-list'))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         'Expecting Location to be created successfully')
        location = Location.get_if_exists(uid='Aplinkkelis')
        data = LocationQuickSerializer(instance=location).data
        self.assertEqual(data,
                         {
                             'id': 'APLINKKELIS', 'name': 'IONITY High Power Charging Aplinkkelis',
                             'address': 'Panevėžio aplinkl. 20', 'city': '-', 'postal_code': '38417', 'country': 'LTU',
                             'time_zone': 'Europe/Vilnius', 'latitude': 55.67309, 'longitude': 24.33591
                         },
                         'New Location data differs from expected')

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
        self.assertEqual(
            data,
            {
                'id': 'EKI1', 'name': "Eki's home charger", 'address': 'Kotikatu 38', 'city': 'Espoo',
                'postal_code': '01234', 'country': 'FIN', 'time_zone': 'Europe/Helsinki', 'latitude': 60.0,
                'longitude': 30.0, 'evses': [OrderedDict([('uid', '1'), ('connectors', [OrderedDict(
                [('uid', '1'), ('standard', 'IEC_62196_T2'), ('format', 'CABLE'), ('max_voltage', 233),
                 ('max_amperage', 32), ('max_electric_power', 22200), ('tariff_ids', ['EKI1'])])])]),
                                             OrderedDict([('uid', '2'), ('connectors', [OrderedDict(
                                                 [('uid', '1'), ('standard', 'IEC_62196_T2'),
                                                  ('format', 'SOCKET'), ('max_voltage', 232),
                                                  ('max_amperage', 32)])])]),
                                             OrderedDict([('uid', 'JAAU254040-1'), ('connectors', [
                                                 OrderedDict([('uid', '1'), ('standard', 'IEC_62196_T2'),
                                                              ('format', 'CABLE'), ('max_voltage', 233),
                                                              ('max_amperage', 32),
                                                              ('tariff_ids', ['DC50'])])])])]
            },
            'New Location data differs from expected')

        #
        # Update Location
        #

        response = patch_location(test_data.LocationData.location_update1, reverse('quick-location-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         'Expecting Location to be updated successfully')
        location = Location.get_if_exists(uid=test_data.LocationData.location_update1.get('id'))
        data = LocationQuickSerializer(instance=location).data
        self.assertEqual(
            data,
            {
                'id': 'EKI1', 'name': "Eki's home charger", 'address': 'Kotikatu 38', 'city': 'Espoo',
                'postal_code': '01234', 'country': 'FIN', 'time_zone': 'Europe/Helsinki', 'latitude': 60.0,
                'longitude': 30.0,
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
            },
            'Updated Location data differs from expected')


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
