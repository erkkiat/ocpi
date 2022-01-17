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
from icecream import ic
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.api import TariffViewSet, TariffSerializer, CdrViewSet, CdrSerializer, TokenViewSet, TokenSerializer
from ocpi22.location import LocationViewSet
from ocpi22.models.models import BusinessDetails
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.tariff import Tariff, TariffElement, PriceComponent
from ocpi22.models.cdr import Cdr
from ocpi22.models.token import Token
from ocpi22.util import OCPIResponse, Ocpi


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.util'))
    tests.addTests(doctest.DocTestSuite('ocpi22.location'))
    # tests.addTests(doctest.DocTestSuite('chargers.vendors.tesla'))
    return tests


def create_tariff(*_args, **kwargs) -> Tariff:
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


class OcpiTests(TestCase):
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
            city='City', country='FIN', latitude=60.0, longitude=30.0, time_zone='Helsinki/Finland'
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

    def put(self, url, data, token, viewset) -> OCPIResponse:
        request = self.factory.put(url, data, content_type="application/json",
                                   Authorization=f'Token {token}')
        request.data = data
        request.user = AnonymousUser
        request.credentials = self.credentials

        return viewset().put(request)

    def test_put_location(self):
        url = reverse('location-list')
        dirname = os.path.dirname(os.path.abspath(__file__))
        token_base64 = self.credentials.ours_base64()

        invalid_data = dict(country_code=self.country_code, party_id=self.party_id, id=123)

        response = self.put(url, invalid_data, 'FALSETOKEN', LocationViewSet)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'A Location request should require OCPI authentication. '
                         f'{response.data}')
        self.assertEqual(response.data['status_code'], Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                         'The response OCPI status should be INVALID_OR_MISSING_PARAMETERS. '
                         f'{response.data}')

        response = self.put(url, invalid_data, token_base64, LocationViewSet)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'Badly formed but correctly authenticated request should produce http status code 400.')

        testcases = (
            # Create a Location and then update it by adding one more Connector and then an Evse with a Connector
            ('location_example', 'BE', 'BEC', status.HTTP_201_CREATED, 1000, ['11', '12', '13'], 2, 3),
            ('location_example_added_connector', 'BE', 'BEC', status.HTTP_200_OK, 1000, [], 2, 4),
            ('location_example_added_evse', 'BE', 'BEC', status.HTTP_200_OK, 1000, [], 3, 5),

            ('location_example_parking_garage_opening_hours', 'SE', 'EVC', status.HTTP_201_CREATED, 1000, [],
             1, 1),

            ('location_example_uc2_destination_charger', 'NL', 'ALF', status.HTTP_201_CREATED, 1000, [],
             1, 1),
            ('location_example_uc3_destination_charger_not_published', 'NL', 'ALF', status.HTTP_200_OK, 1000, [],
             1, 1),
            ('location_example_uc3_destination_charger_not_published', 'NL', 'ALF', status.HTTP_200_OK, 1000, [],
             1, 1),

            # Todo: Implement parking_restrictions

            ('location_example_uc4_limited_visibility', 'NL', 'ALL', status.HTTP_201_CREATED, 1000, [],
             1, 1),

            # Todo: Check for publish_allowed_to below

            ('location_example_uc5_home_charge_point', 'DE', 'ALL', status.HTTP_201_CREATED, 1000, [],
             1, 1),
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

        for filename, country_code, party_id, http_status, ocpi_status, tariffs, evses, connectors in testcases:

            with open(os.path.join(dirname, f'data/examples/{filename}.json')) as file:
                data = json.load(file)

            # Create the needed Tariffs
            for t in tariffs:
                create_tariff(uid=t, country_code=country_code, party_id=party_id)

            # And CretentialsRoles
            # noinspection PyUnresolvedReferences
            roles, _created = CredentialsRole.objects.get_or_create(role='CPO', country_code=country_code,
                                                    party_id=party_id, defaults=dict(business_details=self.business_details))
            self.credentials.roles.add(roles)

            # Send the request
            response = self.put(url, data, token_base64, LocationViewSet)
            # if response.status_text:
            #     print(f'status_text: "{response.status_text}" for {filename} case.')
            self.assertEqual(response.status_code, http_status,
                             f'Expected a HTTP status code {http_status} for {filename} case.')
            self.assertEqual(response.data['status_code'], ocpi_status,
                             f'Expected an OCPI status code {ocpi_status} for {filename} case.')

            if evses:
                uid = data.get('id').upper()
                # noinspection PyUnresolvedReferences
                try:
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
                except Location.DoesNotExist:
                    print(f'Unable to fetch Location {uid} created from file {filename}.')
                    # noinspection PyUnresolvedReferences
                    self.fail(f'Possible options are: {", ".join([l.uid for l in Location.objects.all()])}')


    def test_put_tariff(self):
        url = reverse('tariff-list')
        dirname = os.path.dirname(os.path.abspath(__file__))
        token_base64 = self.credentials.ours_base64()

        invalid_data = dict(country_code=self.country_code, party_id=self.party_id, id=123)

        response = self.put(url, invalid_data, 'FALSETOKEN', TariffViewSet)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'A Tariff request should require OCPI authentication. '
                         f'{response.data}')
        self.assertEqual(response.data['status_code'], Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                         'The response OCPI status should be INVALID_OR_MISSING_PARAMETERS. '
                         f'{response.data}')

        testcases = (
            ('tariff_1_simple_2hour', 'DE', 'ALL', status.HTTP_201_CREATED, 1000, 1),
            ('tariff_1_simple_2hour_modified', 'DE', 'ALL', status.HTTP_200_OK, 1000, 2),
        )

        for filename, country_code, party_id, http_status, ocpi_status, price_component_count \
                in testcases:

            with open(os.path.join(dirname, f'data/examples/{filename}.json')) as file:
                data = json.load(file)

            # Create CretentialsRoles
            # noinspection PyUnresolvedReferences
            roles, _created = CredentialsRole.objects.get_or_create(role='CPO', country_code=country_code,
                                                    party_id=party_id, defaults=dict(business_details=self.business_details))
            self.credentials.roles.add(roles)

            # Send the request
            response = self.put(url, data, token_base64, TariffViewSet)
            # if response.status_text:
            #     print(f'status_text: "{response.status_text}" for {filename} case.')
            self.assertEqual(response.status_code, http_status,
                             f'Expected a HTTP status code {http_status} for {filename} case.')
            self.assertEqual(response.data['status_code'], ocpi_status,
                             f'Expected an OCPI status code {ocpi_status} for {filename} case.')

            # Verify the saved data
            uid = data.get('id')
            saved_data = TariffSerializer(Tariff.objects.get(uid=uid, archived=False)).data
            # ic(saved_data)

            # Make sure that the received last_updated timestamp will be stored and not overwritten by timezone.now()
            self.assertEqual(saved_data.get('last_updated'), data.get('last_updated').rstrip('Z'),
                             'Last_updated is not stored from the incoming data')

            # Check that there are all three levels stored from the incoming JSON
            elements_list = saved_data.get('elements')
            self.assertIsInstance(elements_list, list,
                                  'TariffElements list is missing from the stored Tariff')
            self.assertTrue(len(elements_list), 'Stored TariffElement list is empty')
            for el in elements_list:
                price_components_list = el.get('price_components')
                self.assertIsInstance(price_components_list, list,
                                      'PriceComponents list is missing from the stored Tariff')
                self.assertEqual(len(price_components_list), price_component_count,
                                f'There should be exactly {price_component_count} '
                                f'PriceComponents in the Tariff after {filename}.json')
                for pc in price_components_list:
                    self.assertTrue(pc.get('type'),
                                    'Looks like TariffSerializer is not storing PriceComponents')

    def test_put_cdr(self):
        url = reverse('cdr-list')
        dirname = os.path.dirname(os.path.abspath(__file__))
        token_base64 = self.credentials.ours_base64()
        viewset = CdrViewSet

        invalid_data = dict(country_code=self.country_code, party_id=self.party_id, id=123)

        response = self.put(url, invalid_data, 'FALSETOKEN', viewset)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         f'A {viewset} request should require OCPI authentication. '
                         f'{response.data}')
        self.assertEqual(response.data['status_code'], Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                         f'The {viewset} response OCPI status should be INVALID_OR_MISSING_PARAMETERS. '
                         f'{response.data}')

        testcases = (
            ('cdr_example', status.HTTP_201_CREATED, 1000, 1),
        )

        for filename, http_status, ocpi_status, price_component_count \
                in testcases:

            with open(os.path.join(dirname, f'data/examples/{filename}.json')) as file:
                data = json.load(file)

            country_code = data.get('country_code')
            party_id = data.get('party_id')

            # Create CretentialsRoles
            roles, _created = CredentialsRole.objects.get_or_create(role='CPO', country_code=country_code,
                                                    party_id=party_id, defaults=dict(business_details=self.business_details))
            self.credentials.roles.add(roles)

            # Send the request
            response = self.put(url, data, token_base64, viewset)
            # if response.status_text:
            #     print(f'status_text: "{response.status_text}" for {filename} case.')
            #     ic(response.data)
            self.assertEqual(response.status_code, http_status,
                             f'Expected a HTTP status code {http_status} for {filename} case.')
            self.assertEqual(response.data['status_code'], ocpi_status,
                             f'Expected an OCPI status code {ocpi_status} for {filename} case.')

            # Verify the saved data
            uid = data.get('id')
            # noinspection PyUnresolvedReferences
            saved_data = CdrSerializer(Cdr.objects.get(uid=uid)).data
            # ic(saved_data)

            # Make sure that the received last_updated timestamp will be stored and not overwritten by timezone.now()
            self.assertEqual(saved_data.get('last_updated'), data.get('last_updated').rstrip('Z'),
                             'Last_updated is not stored from the incoming data')

    def test_put_token(self):
        url = reverse('token-list')
        dirname = os.path.dirname(os.path.abspath(__file__))
        token_base64 = self.credentials.ours_base64()
        viewset = TokenViewSet

        # invalid_data = dict(country_code=self.country_code, party_id=self.party_id, id=123)
        #
        # response = self.put(url, invalid_data, 'FALSETOKEN', viewset)
        # self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
        #                  f'A {viewset} request should require OCPI authentication. '
        #                  f'{response.data}')
        # self.assertEqual(response.data['status_code'], Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        #                  f'The {viewset} response OCPI status should be INVALID_OR_MISSING_PARAMETERS. '
        #                  f'{response.data}')

        testcases = (
            ('token_example_2_full_rfid', status.HTTP_201_CREATED, 1000),
            ('token_example_2_full_rfid_modified', status.HTTP_200_OK, 1000),
            ('token_example_1_app_user', status.HTTP_201_CREATED, 1000),
        )

        for filename, http_status, ocpi_status \
                in testcases:

            with open(os.path.join(dirname, f'data/examples/{filename}.json')) as file:
                data = json.load(file)

            country_code = data.get('country_code')
            party_id = data.get('party_id')

            # Create CretentialsRoles
            # noinspection PyUnresolvedReferences
            roles, _created = CredentialsRole.objects.get_or_create(role='CPO', country_code=country_code,
                                                    party_id=party_id, defaults=dict(business_details=self.business_details))
            self.credentials.roles.add(roles)

            # Send the request
            response = self.put(url, data, token_base64, viewset)
            # if response.status_text:
            #     print(f'status_text: "{response.status_text}" for {filename} case.')
            #     ic(response.data)
            self.assertEqual(response.status_code, http_status,
                             f'Expected a HTTP status code {http_status} for {filename} case.')
            self.assertEqual(response.data['status_code'], ocpi_status,
                             f'Expected an OCPI status code {ocpi_status} for {filename} case.')

            try:
                # Verify the saved data
                uid = data.get('uid').upper()
                # noinspection PyUnresolvedReferences
                saved_data = TokenSerializer(Token.objects.get(uid=uid)).data
                # ic(saved_data)
            except Token.DoesNotExist as e:
                print(f"Unable to verify token {uid} from database.")
                print('Available Tokens:')
                for t in Token.objects.all():
                    print(t)
                raise

            # Make sure that the received last_updated timestamp will be stored and not overwritten by timezone.now()
            self.assertEqual(saved_data.get('last_updated'), data.get('last_updated').rstrip('Z'),
                             'Last_updated is not stored from the incoming data')

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


class TariffTests(TestCase):

    def dump_tariffs(self):
        # noinspection PyUnresolvedReferences
        for t in Tariff.objects.all():
            serializer = TariffSerializer(t)
            ic(t.pk, serializer.data)

    def check_tariff(self, tariff, tariff_elements, price_components):
        self.assertEqual(tariff.tariff_elements.count(), tariff_elements,
                         f"Tariff #{tariff.pk} `{tariff}` doesn't have {tariff_elements} TariffElements")
        for e in tariff.tariff_elements.all():
            self.assertEqual(e.price_components.count(), price_components,
                             f"TariffElement #{e.pk} `{e}` doesn't have {price_components} PriceComponents")

    # noinspection PyUnresolvedReferences
    def test_tariff_copying(self):
        Tariff.objects.all().delete()
        # Create some Tariffs
        t1 = create_tariff(uid='T1', country_code='FI', party_id='ABC')
        # self.dump_tariffs()
        t1_copy = Tariff.make_copy(t1)
        self.check_tariff(t1_copy, 1, 1)
        # self.dump_tariffs()
        self.assertEqual(Tariff.objects.count(), 2, 'There should be exactly 2 Tariffs after creating copies')
