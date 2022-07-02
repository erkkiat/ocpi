import doctest
from unittest import TestCase

from django.contrib.auth.models import AnonymousUser
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.cpo.api import LocationQuickViewSet
from ocpi22.cpo.serializers import LocationQuickSerializer
from ocpi22.models.location import Location

api_factory = APIRequestFactory()


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.cpo.util'))
    return tests


class TestQuickLocations(TestCase):
    maxDiff = 99999

    def test_quick_location(self):
        #
        # Test new location outside of any cities, coordinates as string
        #

        location = Location.get_if_exists(uid='Aplinkkelis')
        if location:
            location.delete()

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
        # Try updating Location data
        #

        data = {
            "id": "Aplinkkelis",
            "name": "IONITY High Power Charging Aplinkkelis",
            "latitude": 42.6975216,
            "longitude": 23.3191493
        }
        response = patch_location(data, reverse('quick-location-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         'Expecting Location to be updated successfully')
        location = Location.get_if_exists(uid='Aplinkkelis')
        data = LocationQuickSerializer(instance=location).data
        self.assertEqual(data,
                         {
                             'id': 'Aplinkkelis', 'name': 'IONITY High Power Charging Aplinkkelis',
                             'address': 'Knyaz Boris Ⅰ 134', 'city': 'Sofia', 'postal_code': '1000', 'country': 'BGR',
                             'time_zone': 'Europe/Sofia', 'latitude': 42.6975216, 'longitude': 23.3191493
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
