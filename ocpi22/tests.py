import doctest
import json
import os

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30} // [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-
#  Za-z0-9\*]{0,30}
# Todo: Tariff_id: Regular Expression: [A-Z]{2}[A-Za-z0-9]{3}[T][A-Z0-9][A-Z0-9\*]{0,29}
# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}
#                                   [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}   ????
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.location import LocationViewSet
from ocpi22.models import Credentials, Location, Evse, Connector, CredentialsRole, BusinessDetails, Tariff, \
    PriceComponent, TariffElement
from ocpi22.util import OCPIResponse, Ocpi


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.util'))
    # tests.addTests(doctest.DocTestSuite('chargers.vendors.tesla'))
    return tests


class LocationTests(TestCase):
    fixtures = ['ocpi22/data/initial.json']
    location_index = 1
    factory = APIRequestFactory()
    country_code = 'FI'
    party_id = 'XXX'

    # noinspection PyUnresolvedReferences
    def create_location(self, uid=None, address='Testroad 1', name='Name', location_status='AVAILABLE') -> Location:
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
            evse = Evse.objects.create(status=location_status, uid=i, location=location)
            for n in range(1, 5):
                Connector.objects.create(uid=n, evse=evse, standard='IEC_62196_T2',
                                         format='SOCKET', power_type='AC_3_PHASE', max_voltage=230, max_amperage=96,
                                         )
        return location

    # noinspection PyUnresolvedReferences
    def setUp(self):
        self.location = self.create_location()
        self.credentials = Credentials.objects.create(token_a='TOKEN_A', ours='OURS', theirs='THEIRS')
        self.business_details = BusinessDetails.objects.create(name='Test Business')
        roles1 = CredentialsRole.objects.create(role='CPO', country_code=self.country_code,
                                                party_id=self.party_id, business_details=self.business_details)
        self.credentials.roles.set([roles1])

    @staticmethod
    # noinspection PyUnresolvedReferences
    def create_tariff(*_args, **kwargs):
        params = dict(
            currency='EUR'
        )
        params.update(kwargs)
        tariff = Tariff.objects.create(**params)
        # noinspection PyUnresolvedReferences
        tariff_element = TariffElement.objects.create(tariff=tariff)
        # noinspection PyUnresolvedReferences
        PriceComponent.objects.create(type='FLAT', price=1.0, step_size=1, tariff_element=tariff_element)
        return tariff

    def test_evse_with_same_id(self):
        # Create two locations with the same Evse IDs
        location1 = self.create_location()
        location2 = self.create_location()

    def test_evse_format(self):
        loc = self.create_location()
        # noinspection PyUnresolvedReferences
        evse = loc.evses.all()[0]
        url = reverse('location-by-evse-id',
                      args=[loc.country_code, loc.party_id, loc.uid, evse.uid])

        request = self.factory.get(url)
        viewset = LocationViewSet()
        response = viewset.by_evse_id(request, loc.country_code, loc.party_id, loc.uid, evse.uid)
        data = response.data.get('data')
        self.assertIsInstance(data, dict, msg='There should be a dict element "data" in the EVSE')
        connectors = data.get('connectors')
        self.assertIsInstance(connectors, list, msg='EVSE connectors should be a list')
        self.assertEqual(response.data.get('status_code'), 1000, msg='OCPI status code should be 1000 for success')

    def test_location_by_id(self):
        url = reverse('location-by-id',
                      args=[self.location.country_code, self.location.party_id, self.location.uid])

        request = self.factory.get(url)
        loc = self.location
        viewset = LocationViewSet()
        response = viewset.by_id(request, loc.country_code, loc.party_id, loc.uid)
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

    def put(self, url, data, token) -> OCPIResponse:
        request = self.factory.put(url, data, content_type="application/json",
                                   Authorization=f'Token {token}')
        request.data = data
        request.user = AnonymousUser
        request.credentials = self.credentials

        viewset = LocationViewSet()
        return viewset.put(request)

    def test_put_location(self):
        url = reverse('location-list')
        dirname = os.path.dirname(os.path.abspath(__file__))
        token_base64 = self.credentials.ours_base64()

        invalid_data = dict(country_code=self.country_code, party_id=self.party_id, id=123)

        response = self.put(url, invalid_data, 'FALSETOKEN')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'A Location request should require OCPI authentication. '
                         f'{response.data}')
        self.assertEqual(response.data['status_code'], Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                         'The response OCPI status should be INVALID_OR_MISSING_PARAMETERS. '
                         f'{response.data}')

        response = self.put(url, invalid_data, token_base64)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'Badly formed but correctly authenticated request should produce http status code 400.')

        testcases = (
            # Create a Location and then update it by adding one more Connector and then an Evse with a Connector
            ('location_example', 'BE', 'BEC', status.HTTP_201_CREATED, 1000, ['11', '12', '13'], 'LOC1', 2, 3),
            ('location_example_added_connector', 'BE', 'BEC', status.HTTP_200_OK, 1000, [], 'LOC1', 2, 4),
            ('location_example_added_evse', 'BE', 'BEC', status.HTTP_200_OK, 1000, [], 'LOC1', 3, 5),

            ('location_example_parking_garage_opening_hours', 'SE', 'EVC', status.HTTP_201_CREATED, 1000, [],
             'cbb0df21-d17d-40ba-a4aa-dc588c8f98cb', 1, 1),

            ('location_example_uc2_destination_charger', 'NL', 'ALF', status.HTTP_201_CREATED, 1000, [],
             '3e7b39c2-10d0-4138-a8b3-8509a25f9920', 1, 1),
            ('location_example_uc3_destination_charger_not_published', 'NL', 'ALF', status.HTTP_200_OK, 1000, [],
             '3e7b39c2-10d0-4138-a8b3-8509a25f9920', 1, 1),
            ('location_example_uc3_destination_charger_not_published', 'NL', 'ALF', status.HTTP_200_OK, 1000, [],
             '3e7b39c2-10d0-4138-a8b3-8509a25f9920', 1, 1),

            # Todo: Implement parking_restrictions

            ('location_example_uc4_limited_visibility', 'NL', 'ALL', status.HTTP_201_CREATED, 1000, [],
             'f76c2e0c-a6ef-4f67-bf23-6a187e5ca0e0', 1, 1),

            # Todo: Check for publish_allowed_to below

            ('location_example_uc5_home_charge_point', 'DE', 'ALL', status.HTTP_201_CREATED, 1000, [],
             'a5295927-09b9-4a71-b4b9-a5fffdfa0b77', 1, 1),
        )

        publish_allowed_to = [{
            "visual_number": "12345-67",
            "issuer": "NewMotion"
        }, {
            "visual_number": "0055375624",
            "issuer": "ANWB"
        }, {
            "uid": "12345678905880",
            "type": "RFID"
        }]

        for filename, country_code, party_id, http_status, ocpi_status, tariffs, \
        uid, evses, connectors in testcases:

            with open(os.path.join(dirname, f'data/examples/{filename}.json')) as file:
                data = json.load(file)

            # Create the needed Tariffs
            for t in tariffs:
                self.create_tariff(uid=t, country_code=country_code, party_id=party_id)

            # And CretentialsRoles
            roles, _created = CredentialsRole.objects.get_or_create(role='CPO', country_code=country_code,
                                                    party_id=party_id, defaults=dict(business_details=self.business_details))
            self.credentials.roles.add(roles)

            # Send the request
            response = self.put(url, data, token_base64)
            # if response.status_text:
            #     print(f'status_text: "{response.status_text}" for {filename} case.')
            self.assertEqual(response.status_code, http_status,
                             f'Expected a HTTP status code {http_status} for {filename} case.')
            self.assertEqual(response.data['status_code'], ocpi_status,
                             f'Expected an OCPI status code {ocpi_status} for {filename} case.')

            # noinspection PyUnresolvedReferences
            location = Location.objects.get(uid=uid)
            # print(f"Evses: {location.evses.count()}")
            self.assertEqual(location.evses.count(), evses, f'There should be {evses} evses after {filename} case.')
            connector_count = 0
            for evse in location.evses.all():
                connector_count += evse.connectors.count()
            # print(f"Connectors: {connector_count}")
            self.assertEqual(connector_count, connectors,
                             f'There should be {connectors} connectors after {filename} case.')

        # This was a specific problem
        response = self.put(
            url,
            json.loads('''
            {"address": "Street 1",
                      "city": "Helsinki",
                      "coordinates": {"latitude": "60.000000", "longitude": "30.000000"},
                      "country": "FIN",
                      "country_code": "BE",
                      "facilities": ["HOTEL"],
                      "id": "UID11",
                      "last_updated": "2022-01-05T06:58:15.811866",
                      "name": "Test location 6",
                      "parking_type": "PARKING_LOT",
                      "party_id": "BEC",
                      "publish": true,
                      "time_zone": "Europe/Helsinki"}
            '''), token_base64)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_patch_connector(self):
        # url = reverse('location-connector', self.location, ...)
        data = dict({
            "tariff_ids": ["15"],
            "last_updated": "2019-06-24T12:39:09Z"
        })

    def test_ocpi(self):
        url = reverse('location-by-id',
                      args=[self.location.country_code, self.location.party_id, self.location.uid])

        request = self.factory.get(url)
        loc = self.location
        viewset = LocationViewSet()
        response = viewset.by_id(request, loc.country_code, loc.party_id, loc.uid)
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
