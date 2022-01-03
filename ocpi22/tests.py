"""
This file demonstrates writing tests using the unittest module. These will pass
when you run "manage.py test".

Replace this with more appropriate tests for your application.
"""
from django.test import TestCase

# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30} // [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-
#  Za-z0-9\*]{0,30}
# Todo: Tariff_id: Regular Expression: [A-Z]{2}[A-Za-z0-9]{3}[T][A-Z0-9][A-Z0-9\*]{0,29}
# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}
#                                   [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}   ????
from icecream import ic
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.location import LocationViewSet
from ocpi22.models import Credentials, Location, Evse, Connector


class LocationTests(TestCase):
    location_index = 1

    # noinspection PyUnresolvedReferences
    def create_location(self, uid=None, address='Testroad 1', name='Name', status='AVAILABLE') -> Location:
        """
        Create a location with multiple Evses, with overlapping Evse IDs (OCPI: Evse ID is unique
        within a party and its suboperators
        """
        if not uid:
            uid = self.location_index
            self.location_index += 1

        location = Location.objects.create(
            uid=uid, name=f"{name} {uid}", country_code='FI', party_id=f"F{uid}", publish=True, address=address,
            city='City', country='Country', latitude=60, longitude=30, time_zone='Helsinki/Finland'
        )
        # Use the same ids to make sure that they are accepted
        for i in range(1, 5):
            evse = Evse.objects.create(status=status, uid=i, location=location)
            for n in range(1, 5):
                Connector.objects.create(uid=n, evse=evse, standard='IEC_62196_T2',
                                         format='SOCKET', power_type='AC_3_PHASE', max_voltage=230, max_amperage=96,
                                         )
        return location

    # noinspection PyUnresolvedReferences
    def setUp(self):
        # self.credentials = Credentials.objects.all()[0]
        self.location = self.create_location()
        pass

    def test_evse_with_same_id(self):
        # Create two locations with the same Evse IDs
        location1 = self.create_location()
        location2 = self.create_location()

    def test_evse_format(self):
        factory = APIRequestFactory()
        l = self.create_location()
        # noinspection PyUnresolvedReferences
        evse = l.evses.all()[0]
        url = reverse('location-by-evse-id',
                      args=[l.country_code, l.party_id, l.uid, evse.uid])

        request = factory.get(url)
        viewset = LocationViewSet()
        response = viewset.by_evse_id(request, l.country_code, l.party_id, l.uid, evse.uid)
        # ic(response, response.data)
        data = response.data.get('data')
        self.assertIsInstance(data, dict, msg='There should be a dict element "data" in the EVSE')
        connectors = data.get('connectors')
        self.assertIsInstance(connectors, list, msg='EVSE connectors should be a list')
        self.assertEqual(response.data.get('status_code'), 1000, msg='OCPI status code should be 1000 for success')

    def test_location(self):
        factory = APIRequestFactory()
        url = reverse('location-by-id',
                      args=[self.location.country_code, self.location.party_id, self.location.uid])

        request = factory.get(url)
        l = self.location
        viewset = LocationViewSet()
        response = viewset.by_id(request, l.country_code, l.party_id, l.uid)
        # ic(response, response.data)
        data = response.data.get('data')
        self.assertIsInstance(data, dict, msg='There should be a dict element "data" in the Location')

        # Coordinates
        coordinates = data.get('coordinates')
        self.assertIsInstance(coordinates, dict)
        latitude = coordinates.get('latitude')
        longitude = coordinates.get('longitude')
        self.assertIsInstance(latitude, str, msg='OCPI: Latitude and longitude should be strings')
        self.assertIsInstance(longitude, str, msg='OCPI: Latitude and longitude should be strings')
        decimals = latitude.split('.')[1]
        self.assertEqual(len(decimals), 6, msg='e-clearing.net: There should be exactly 6 decimals in latitude')
        decimals = longitude.split('.')[1]
        self.assertEqual(len(decimals), 6, msg='e-clearing.net: There should be exactly 6 decimals in longitude')

        # EVSES
        evses = data.get('evses')
        self.assertIsInstance(evses, list, msg='Location EVSEs should be a list')
        for evse in evses:
            connectors = evse.get('connectors')
            self.assertIsInstance(connectors, list, msg='EVSE connectors should be a list')

    def test_ocpi(self):
        factory = APIRequestFactory()
        url = reverse('location-by-id',
                      args=[self.location.country_code, self.location.party_id, self.location.uid])

        request = factory.get(url)
        l = self.location
        viewset = LocationViewSet()
        response = viewset.by_id(request, l.country_code, l.party_id, l.uid)
        # ic(response, response.data)
        data = response.data.get('data')

        self.assertEqual(response.data.get('status_code'), 1000, msg='OCPI status code should be 1000 for success')

        detail_url = data.get('detail_url')

        # This should fail without authentication
        result = self.client.get(detail_url)
        self.assertEqual(result.status_code, 403, 'A Location request should require OCPI authentication.')

        # Todo: Create Credentials or preferably negotiate them with self
        # # Fail with the other party's token
        # result = self.client.get(detail_url, HTTP_AUTHORIZATION=f'Token {self.credentials.theirs_base64()}')
        # self.assertEqual(result.status_code, 403, "OCPI token authentication allows the other party's token.")
        #
        # # Fail with token_a after the credentials exchange has been done
        # result = self.client.get(detail_url, HTTP_AUTHORIZATION=f'Token {self.credentials.token_a_base64()}')
        # self.assertEqual(result.status_code, 403,
        #                  "OCPI token authentication allows token_a after the credentials exchange has been finished.")
        #
        # # ...and work with a proper OCPI token
        # url = f'{detail_url}?auth-test={self.credentials.ours_base64()}'
        # result = self.client.get(url)
        # self.assertEqual(result.status_code, 200, 'Token auth-test seems not to work.')
        #
        # result = self.client.get(detail_url, HTTP_AUTHORIZATION=f'Token {self.credentials.ours_base64()}')
        # self.assertEqual(result.status_code, 200, 'OCPI token authentication seems not to work.')
        #
