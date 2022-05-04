import doctest
import json
import os
import logging
import uuid
from collections import OrderedDict
from dataclasses import asdict

from datetime import timedelta, datetime
from unittest.mock import Mock, patch

import pytz
import time_machine
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, RequestFactory, Client

# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30} // [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-
#  Za-z0-9\*]{0,30}
# Todo: Tariff_id: Regular Expression: [A-Z]{2}[A-Za-z0-9]{3}[T][A-Z0-9][A-Z0-9\*]{0,29}
# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}
#                                   [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}   ????
from icecream import ic
from requests import Response
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.ocpi.api import TariffViewSet, CdrViewSet, TokenViewSet, SessionViewSet
from ocpi22.ocpi.serializers import TokenSerializer, TariffSerializer, CdrSerializer, SessionSerializer
from ocpi22.choices import OcpiModuleEnum
from ocpi22.commands.commands import CommandsViewSet
from ocpi22.commands.serializers import CommandResponse
from ocpi22.cpo.api import ChargePointViewSet
from ocpi22.locations.location import LocationViewSet
from ocpi22.locations.serializers import LocationSaveSerializer
from ocpi22.middleware import OCPIHubMiddleware
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.credentials import Credentials, CredentialsRole, find_endpoints_by_roles
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.tariff import Tariff, TariffElement, PriceComponent
from ocpi22.models.cdr import Cdr
from ocpi22.models.token import Token
from ocpi22.ocpi.util import OCPIResponse, Ocpi, OcpiModule
from ocpi22.ocpi.headers import make_headers
from ocpi22.pull import schedule_full_update
from ocpi22.routing import find_route, Route
from ocpi22.sessions.util import create_session
from ocpi22.test_data import ocpi_endpoints_response, expected_get_headers, \
    accept_authorization, ExpectedSessionUpdateResults
from ocpi22.tokens.auth import authorize_token, _get_authorization_from_sessions, _authorize_token
from ocpi22.tokens.util import get_admin_token
from ocpi22.util import is_our_identifier
from ocpiconnector.management.commands import exchange_credentials
from ocpi22.test_data import expected_get_responses
from ocpiconnector.ocpi_identities import Party

faketime = datetime(2000, 1, 1, 12, 0)
client = Client()
dirname = os.path.dirname(os.path.abspath(__file__))
api_factory = APIRequestFactory()


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.ocpi.api'))
    tests.addTests(doctest.DocTestSuite('ocpi22.util'))
    tests.addTests(doctest.DocTestSuite('ocpi22.ocpi.util'))
    tests.addTests(doctest.DocTestSuite('ocpi22.locations.location'))
    tests.addTests(doctest.DocTestSuite('ocpi22.locations.serializers'))
    tests.addTests(doctest.DocTestSuite('ocpi22.commands.commands'))
    tests.addTests(doctest.DocTestSuite('ocpi22.commands.serializers'))
    tests.addTests(doctest.DocTestSuite('ocpi22.models.dynamic_price'))
    tests.addTests(doctest.DocTestSuite('ocpi22.tasks'))
    tests.addTests(doctest.DocTestSuite('ocpi22.models.tariff'))
    tests.addTests(doctest.DocTestSuite('ocpiconnector.management.commands.exchange_credentials'))
    tests.addTests(doctest.DocTestSuite('ocpiconnector.settings'))
    tests.addTests(doctest.DocTestSuite('ocpiconnector.ocpi_identities'))
    return tests


def load_example(filename: str) -> dict:
    with open(os.path.join(dirname, filename)) as file:
        return json.load(file)


def create_tariff(*_args, **kwargs) -> Tariff:
    params = dict(
        currency='EUR'
    )
    params.update(kwargs)
    # noinspection PyUnresolvedReferences
    tariff = Tariff.objects.create(**params)
    # noinspection PyUnresolvedReferences
    tariff_element = TariffElement.objects.create(tariff=tariff)
    # noinspection PyUnresolvedReferences
    PriceComponent.objects.create(type='FLAT', price=1.0, step_size=1, tariff_element=tariff_element)
    return tariff


def make_sure_no_min_price(tariff: Tariff) -> bool:
    return not tariff.min_price_excl_vat and not tariff.min_price_incl_vat


class ApiPutTests(TestCase):
    fixtures = ['ocpi22/data/initial.json']
    location_index = 1
    country_code = 'FI'
    party_id = 'XXX'
    maxDiff = None

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
        logging.disable(logging.CRITICAL)
        self.location = self.create_location()
        self.credentials = Credentials.objects.create(token_a='TOKEN_A', ours='OURS', theirs='THEIRS')
        self.business_details = BusinessDetails.objects.create(name='Test Business')
        roles1 = CredentialsRole.objects.create(role='CPO', country_code=self.country_code,
                                                party_id=self.party_id, business_details=self.business_details)
        self.credentials.roles.set([roles1])

    def test_evse_with_same_id(self):
        # Create two locations with the same Evse IDs
        _location1 = self.create_location()
        _location2 = self.create_location()

    def test_evse_format(self):
        loc = self.create_location()
        # noinspection PyUnresolvedReferences
        evse = loc.evses.all()[0]
        url = reverse('location-by-evse-id',
                      args=[loc.country_code, loc.party_id, loc.uid, evse.uid])

        request = api_factory.get(url)
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

        request = api_factory.get(url)
        loc = self.location
        viewset = LocationViewSet()
        response = viewset.location_by_id(request, loc.country_code, loc.party_id, loc.uid)
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
        request = api_factory.put(url, data, content_type="application/json",
                                  Authorization=f'Token {token}')
        request.data = data
        request.user = AnonymousUser
        request.credentials = self.credentials

        return viewset().put(request)

    def test_put_location(self):
        url = reverse('location-list')
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

        _publish_allowed_to = [{
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

            data = load_example(f'data/examples/{filename}.json')

            # Create the needed Tariffs
            for t in tariffs:
                create_tariff(uid=t, country_code=country_code, party_id=party_id)

            # And CretentialsRoles
            # noinspection PyUnresolvedReferences
            roles, _created = CredentialsRole.objects.get_or_create(
                role='CPO', country_code=country_code,
                party_id=party_id, defaults=dict(
                    business_details=self.business_details)
            )
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
                    self.assertEqual(location.evses.count(), evses,
                                     f'There should be {evses} evses after {filename} case.')
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
            ('tariff_1_simple_2hour', status.HTTP_201_CREATED, 1000, 1),
            ('tariff_1_simple_2hour_modified', status.HTTP_200_OK, 1000, 2),
            ('tariff_4_complex', status.HTTP_201_CREATED, 1000, 6),
            ('tariff_5_free_of_charge', status.HTTP_201_CREATED, 1000, 1),
            ('tariff_7_first_hour_kwh_free', status.HTTP_201_CREATED, 1000, 5),
            ('tariff_8_simple_025kwh', status.HTTP_201_CREATED, 1000, 1),
            ('tariff_9_025kwh_start', status.HTTP_201_CREATED, 1000, 2),
            ('tariff_10_025kwh_parking_start', status.HTTP_201_CREATED, 1000, 3),
            ('tariff_11_not_possible_alt_text', status.HTTP_201_CREATED, 1000, 2),
            ('tariff_12_025kwh_min_price', status.HTTP_201_CREATED, 1000, 1),
            ('tariff_12_025kwh', status.HTTP_200_OK, 1000, 1,
             dict(check_function=make_sure_no_min_price)),
            ('tariff_13_simple_3hour_5parking', status.HTTP_201_CREATED, 1000, 2),
            ('tariff_14_step_size', status.HTTP_201_CREATED, 1000, 5),
            ('tariff_15_reservation_5_euro_per_hour', status.HTTP_200_OK, 1000, 3),
            ('tariff_16_reservation_2_euro_fee_5_euro_per_hour', status.HTTP_200_OK, 1000, 4),
            ('tariff_17_reservation_with_expire_fee', status.HTTP_200_OK, 1000, 4),
            ('tariff_18_reservation_with_expire_time', status.HTTP_200_OK, 1000, 4),
            ('tariff_put_example', status.HTTP_200_OK, 1000, 1),
            ('tariffrestriction_example_max_duration', status.HTTP_201_CREATED, 1000, 3),
            ('tariffrestriction_example_max_power', status.HTTP_201_CREATED, 1000, 3),
        )

        for filename, http_status, ocpi_status, price_component_count, *extra \
                in testcases:

            data = load_example(f'data/examples/{filename}.json')

            # ic(filename, data.get('id'))
            country_code = data.get('country_code')
            party_id = data.get('party_id')

            self._create_credentials(country_code, party_id)

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
            # noinspection PyUnresolvedReferences
            tariff = Tariff.objects.get(uid=uid, archived=False)
            saved_data = TariffSerializer(tariff).data
            # ic(saved_data)
            last_updated = data.get('last_updated')

            if last_updated:
                # Make sure that the received last_updated timestamp will be stored and not overwritten by timezone.now()
                self.assertEqual(saved_data.get('last_updated'), last_updated,
                                 f'Last_updated is not stored from the incoming data with file {filename}')

            # Check that there are all three levels stored from the incoming JSON
            elements_list = saved_data.get('elements')
            self.assertIsInstance(elements_list, list,
                                  'TariffElements list is missing from the stored Tariff')
            self.assertTrue(len(elements_list), 'Stored TariffElement list is empty')
            total_price_components = 0
            for el in elements_list:
                price_components_list = el.get('price_components')
                total_price_components += len(price_components_list)
                self.assertIsInstance(price_components_list, list,
                                      'PriceComponents list is missing from the stored Tariff')
                for pc in price_components_list:
                    self.assertTrue(pc.get('type'),
                                    'Looks like TariffSerializer is not storing PriceComponents')
            self.assertEqual(total_price_components, price_component_count,
                             f'There should be exactly {price_component_count} '
                             f'PriceComponents in the Tariff after {filename}.json')
            if extra:
                check_function = extra[0].get('check_function')
                if check_function:
                    self.assertTrue(check_function(tariff), f'Check function failed for {filename}')

    def test_cost_calculation(self):
        start_date_time = datetime(2000, 1, 1, 0, 0)
        # noinspection PyUnresolvedReferences
        evse = Evse.objects.all().first()
        location = evse.location
        session_params = dict(
            country_code='FI', party_id='FFF', start_date_time=start_date_time,
            cdr_token_uid='123', cdr_token_type='RFID', cdr_token_contract_id='123', auth_method='COMMAND',
            location=location, evse=evse, currency='EUR', status='ACTIVE',
            end_date_time=start_date_time + timedelta(hours=1)
        )
        testcases = (
            ('tariff_1_simple_2hour', dict(stop_kwh=1, end_date_time=start_date_time + timedelta(hours=2.5)), 5, 5.5),
            ('tariff_8_simple_025kwh', dict(stop_kwh=20), 5, 5.5),
            ('tariff_9_025kwh_start', dict(stop_kwh=20), 5.5, 6.1),
            ('tariff_12_025kwh_min_price', dict(stop_kwh=20), 5, 5.5),
            ('tariff_12_025kwh_min_price', dict(stop_kwh=1), .5, .55),

            # ('tariff_10_025kwh_parking_start', dict(stop_kwh=20, parking=40*60), 7, 7.9),
            ('tariff_6_025kwh_start_max_price', dict(stop_kwh=50), 10, 11),
            ('tariff_6_025kwh_start_max_price', dict(stop_kwh=30), 8, 8.85),

            # Parking
            # ('tariff_13_simple_3hour_5parking', dict(stop_kwh=20)),
            ('tariff_2_alt_text', dict(stop_kwh=1, end_date_time=start_date_time + timedelta(hours=2.5)), 4.75, 5),
            ('tariff_3_alt_url', dict(stop_kwh=20.45), 5.63, 6.24),

            # Parking, weekdays, times
            # ('tariff_4_complex', dict(stop_kwh=20.45), 5.63, 6.24),

        )
        for filename, case_params, excl_vat, incl_vat in testcases:
            params = session_params.copy()
            params.update(case_params)
            # noinspection PyUnresolvedReferences
            session: Session = Session.objects.create(uid=uuid.uuid4().hex,
                                                      **params)
            data = load_example(f'data/examples/{filename}.json')
            serializer = TariffSerializer(data=data)
            self.assertTrue(serializer.is_valid(),
                            f"Tariff doesn't serialize for file {filename}: {serializer.errors}")
            tariff = serializer.save()
            self.assertTrue(session.calculate_price(tariffs=[tariff]), 'Cannot calculate price.')
            # ic(filename, session.total_cost_excl_vat, session.total_cost_incl_vat)
            self.assertEqual(session.total_cost_excl_vat, excl_vat,
                             f"Total cost excluding VAT doesn't match in case {filename}")
            self.assertEqual(session.total_cost_incl_vat, incl_vat,
                             f"Total cost including VAT doesn't match in case {filename}")

    def test_put_cdr(self):
        url = reverse('cdr-list')
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
            ('cdr_example2', status.HTTP_201_CREATED, 1000, 1),
        )

        for filename, http_status, ocpi_status, price_component_count \
                in testcases:

            data = load_example(f'data/examples/{filename}.json')

            country_code = data.get('country_code')
            party_id = data.get('party_id')

            # Create CretentialsRoles
            # noinspection PyUnresolvedReferences
            roles, _created = CredentialsRole.objects.get_or_create(
                role='CPO', country_code=country_code,
                party_id=party_id, defaults=dict(
                    business_details=self.business_details)
            )
            self.credentials.roles.add(roles)

            # Send the request
            response = self.put(url, data, token_base64, viewset)
            if response.status_code >= 300:
                print(f'status_text: "{response.status_text}" for {filename} case.')
                # ic(response.data)
            self.assertEqual(response.status_code, http_status,
                             f'Expected a HTTP status code {http_status} for {filename} case.')
            self.assertEqual(response.data['status_code'], ocpi_status,
                             f'Expected an OCPI status code {ocpi_status} for {filename} case.')

            # Verify the saved data
            uid = data.get('id')
            # noinspection PyUnresolvedReferences
            saved_cdr = Cdr.objects.get(uid=uid)
            saved_data = CdrSerializer(saved_cdr).data
            # ic(saved_data)

            # Check that all Tariffs are archived, so that they won't be modified
            for t in saved_cdr.tariffs.all():
                self.assertTrue(
                    t.archived,
                    'All Tariffs referred to by CDRs must be archived so that they are not modified anymore'
                )

            # Make sure that the received last_updated timestamp will be stored and not overwritten by timezone.now()
            self.assertEqual(saved_data.get('last_updated'), data.get('last_updated'),
                             'Last_updated is not stored from the incoming data')

            # Check that Tariffs are created and are serialized correctly
            tariffs = saved_data.get('tariffs')
            elements = tariffs[0].get('elements')
            price_components = elements[0].get('price_components')

            self.assertTrue(tariffs, 'Tariffs are not stored from the incoming data')
            self.assertTrue(elements, 'TariffElements are not stored from the incoming data')
            self.assertTrue(price_components, 'PriceComponents are not stored from the incoming data')

            # Compare first PriceComponent from JSON data and the saved data
            first_json_price_component = data.get('tariffs')[0].get('elements')[0].get('price_components')[0]
            first_price_component = dict(price_components[0])
            self.assertDictEqual(first_price_component, first_json_price_component,
                                 f'PriceComponent is not stored accurately')

            saved_data = json.loads(json.dumps(saved_data))
            # Remove non-OCPI and unsupported fields
            ignored_fields = ('credit', 'total_time_cost', 'charging_periods', 'tariff_alt_text')
            for i in ignored_fields:
                saved_data.pop(i, None)
                data.pop(i, None)
            for t in range(0, len(saved_data['tariffs'])):
                del saved_data['tariffs'][t]['tariff_alt_text']
            self.assertEqual(saved_data, data)

    def test_put_token(self):
        url = reverse('token-list')
        token_base64 = self.credentials.ours_base64()
        viewset = TokenViewSet

        testcases = (
            ('token_example_2_full_rfid', status.HTTP_201_CREATED, 1000),
            ('token_example_2_full_rfid_modified', status.HTTP_200_OK, 1000),
            ('token_example_1_app_user', status.HTTP_201_CREATED, 1000),
        )

        for filename, http_status, ocpi_status \
                in testcases:

            data = load_example(f'data/examples/{filename}.json')

            country_code = data.get('country_code')
            party_id = data.get('party_id')

            # Create CretentialsRoles
            # noinspection PyUnresolvedReferences
            roles, _created = CredentialsRole.objects.get_or_create(
                role='CPO', country_code=country_code,
                party_id=party_id, defaults=dict(
                    business_details=self.business_details)
            )
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
            uid = data.get('uid').upper()
            # noinspection PyUnresolvedReferences
            try:
                # noinspection PyUnresolvedReferences
                saved_data = TokenSerializer(Token.objects.get(uid=uid)).data
                # ic(saved_data)
            except Token.DoesNotExist:
                print(f"Unable to verify token {uid} from database.")
                print('Available Tokens:')
                # noinspection PyUnresolvedReferences
                for t in Token.objects.all():
                    print(t)
                raise

            # Make sure that the received last_updated timestamp will be stored and not overwritten by timezone.now()
            self.assertEqual(saved_data.get('last_updated'), data.get('last_updated'),
                             'Last_updated is not stored from the incoming data')

    @staticmethod
    def test_patch_connector():
        # url = reverse('location-connector', self.location, ...)
        _data = dict({
            "tariff_ids": ["15"],
            "last_updated": "2019-06-24T12:39:09Z"
        })

    def test_ocpi(self):
        url = reverse('location-by-id',
                      args=[self.location.country_code, self.location.party_id, self.location.uid])

        request = api_factory.get(url)
        loc = self.location
        viewset = LocationViewSet()
        response = viewset.location_by_id(request, loc.country_code, loc.party_id, loc.uid)
        # ic(response, response.data)
        data = response.data.get('data')

        self.assertEqual(response.data.get('status_code'), 1000, msg='OCPI status code should be 1000 for success')

        detail_url = data.get('detail_url')

        # This should fail without authentication
        result = self.client.get(detail_url)
        self.assertTrue(result.status_code in [401, 403], 'A Location request should require OCPI authentication.')

    def _create_credentials(self, country_code, party_id):
        # noinspection PyUnresolvedReferences
        roles, _created = CredentialsRole.objects.get_or_create(
            role='CPO', country_code=country_code,
            party_id=party_id, defaults=dict(business_details=self.business_details)
        )
        self.credentials.roles.add(roles)


def dump_tariffs():
    # noinspection PyUnresolvedReferences
    for t in Tariff.objects.all():
        serializer = TariffSerializer(t)
        ic(t.pk, serializer.data)


class TariffTests(TestCase):
    fixtures = ['ocpi22/data/defaulttariffs.json']

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)

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

    def test_default_tariffs(self):
        tariffs = Tariff.get_default_tariffs('IEC_62196_T2')
        self.assertEqual(tariffs.count(), 1)
        self.assertIsInstance(tariffs[0], Tariff)
        tariff: Tariff = tariffs[0]
        # noinspection PyUnresolvedReferences
        self.assertEqual(tariff.tariff_elements.all()[0].price_components.all()[0].price, 0.22)


class CdrTests(TestCase):
    fixtures = ['ocpi22/data/initial.json', 'ocpi22/data/defaulttariffs.json']

    def load_location(self, filename):
        data = load_example(f'data/examples/{filename}.json')
        serializer = LocationSaveSerializer(data=data)
        if not serializer.is_valid():
            self.fail(serializer.errors)
        return serializer.save()

    def test_session_to_cdr(self):
        for t in [11, 12, 13]:
            create_tariff(uid=str(t), country_code='BE', party_id='BEC')
        location = self.load_location('location_example')
        evse = location.evses.all()[0]
        connector = evse.connectors.all()[0]

        # ic(connector, connector.get_tariffs()[0].price())

        # noinspection PyUnresolvedReferences
        session = Session.objects.create(
            country_code='FI',
            party_id='EON',
            uid='TEST1',
            start_date_time=timezone.now() - timedelta(minutes=30),
            # end_date_time=timezone.now(),
            stop_kwh=12.34,
            cdr_token_uid='TOKEN1',
            cdr_token_type='RFID',
            cdr_token_contract_id='CONTRACT1',
            auth_method=Session.COMMAND,
            authorization_reference='1234567890',
            location=location,
            evse=evse,
            connector=connector,
            meter_id='123',
            currency='EUR',
            total_cost_excl_vat='1.0',
            total_cost_incl_vat='1.24',
            status='COMPLETED',
            last_updated=timezone.now(),
            billed_to='FI*EON'
        )

        # Check that the serializer gives the correct connector ID and Tariff
        serializer = SessionSerializer(session)
        data = serializer.data
        self.assertEqual(data['connector_id'], connector.uid,
                         f"Expecting connector uid {connector.uid}, got {data['connector_id']}")

        self.assertTrue(session.calculate_price(), 'There is sufficient information to calculate the Session price')
        self.assertEqual(session.total_cost_excl_vat, 1, "Price doesn't seem right.")

        cdr1 = Cdr.create_based_on_session(session)

        # Check that Tariffs are archived copies and that they exist

        # noinspection PyUnresolvedReferences
        self.assertTrue(all(t.archived for t in cdr1.tariffs.all()),
                        'Cdr needs to point to only archived Tariffs, so that they are not modified anymore.')

        # noinspection PyUnresolvedReferences
        self.assertEqual(cdr1.tariffs.count(), 1,
                         'Cdr is missing a Tariff')

        # Remove Tariff from Connector, so that the DefaultTariff would be in use
        connector.tariff_ids.set([])

        self.assertTrue(session.calculate_price(), 'There is sufficient information to calculate the Session price')
        self.assertEqual(session.total_cost_excl_vat, 2.86,
                         "Price without VAT doesn't seem right.")
        self.assertEqual(session.total_cost_incl_vat, 3.55,
                         "Price with VAT doesn't seem right.")

        cdr: Cdr = Cdr.create_based_on_session(session)

        # ic(CdrSerializer(cdr).data)
        #
        # ic('All tariffs')
        # for t in Tariff.objects.all():
        #     ic(t.pk, t.references(), TariffSerializer(t).data)
        #
        # ic('CDR tariffs')
        # for t in cdr.tariffs.all():
        #     ic(t.pk, t.archived, t.references(), TariffSerializer(t).data)

        # Check that Tariffs are archived copies and that they exist

        self.assertTrue(all(t.archived for t in cdr.tariffs.all()),
                        'Cdr needs to point to only archived Tariffs, so that they are not modified anymore')

        self.assertEqual(cdr.tariffs.count(), 1,
                         'Cdr is missing a Tariff')

        self.assertEqual(cdr.tariffs.all()[0].uid, 'TTYPE2',
                         'This CDR should have a DefaultTariff, since no Tariff is specified for the Connector')

        self.assertEqual(cdr.billed_to, session.billed_to, 'Billed_to seems not to be copied correctly')


class CommandTests(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {'callback-start_transaction_url': 'http://fakehost/start/{evse_id}/'}.get(x))
    @patch('ocpi22.commands.commands.requests.post')
    def test_start_session(self, requests_post_mock: Mock, _redis_get_mock: Mock):
        # for t in [11, 12, 13]:
        #     create_tariff(uid=str(t), country_code='BE', party_id='BEC')

        url = reverse('commands-start-session')
        viewset = CommandsViewSet()

        # Make sure an empty get doesn't cause validation errors, since we expect the user to just get some instructions
        request = api_factory.get(url)
        request.data = {}
        response = viewset.start_session(request)
        # data = response.data.get('data')
        # ic(response, response.data)

        check_ok_result(self, response)

        # Load up the test message and send it
        data = load_example(f'data/examples/command_start_session.json')

        billed_party = Party('FI', 'EON')
        headers = {
            'Ocpi-From-Country-Code': billed_party.country_code,
            'Ocpi-From-Party-Id': billed_party.party_id
        }
        request = api_factory.post(url, **headers)
        request.data = data
        # noinspection PyUnresolvedReferences
        # request.credentials = Credentials.objects.get(pk=2)

        self.assertFalse(Session.objects.all().exists(),
                         'Please make sure there are no Sessions at the start of this test')

        # Let's pretend to be the CPO and all is good
        requests_post_mock.return_value = make_json_response(dict(result='ACCEPTED'))
        response = viewset.start_session(request)

        # Let's guess the new Session
        session = Session.objects.all().first()
        self.assertEqual(session.billed_to, str(billed_party), 'Billed party appears not to be stored properly')

        check_ok_result(self, response)

        self.assertEqual(response.data.get('data').get('result'), 'ACCEPTED',
                         msg='Expecting the result "ACCEPTED"')

        # noinspection PyUnresolvedReferences
        session = Session.objects.get(status='PENDING')
        self.assertEqual(session.evse.uid, 'HELSINKI-3', "Session UID doesn't match to expected")

        # Let's pick a connector and fill out charging details
        session.connector = session.evse.connectors.all()[0]
        session.stop_kwh = 10.0
        session.total_cost_excl_vat = 4
        session.total_cost_incl_vat = 5
        session.save()

        # ic([(s.uid, s.status) for s in Session.objects.all()])

    def test_unlock_connector(self):
        url = reverse('commands-unlock-connector')
        viewset = CommandsViewSet()

        # Make sure an empty get doesn't cause validation errors, since we expect the user to just get some instructions
        request = api_factory.get(url)
        request.data = {}
        response = viewset.unlock_connector(request)

        check_ok_result(self, response)

        # Load up the test message and send it
        data = load_example(f'data/examples/command_unlock_connector.json')

        request = api_factory.post(url)
        request.data = data
        response = viewset.unlock_connector(request)

        check_ok_result(self, response, command_result=CommandResponse.ACCEPTED)

        data = load_example(f'data/examples/command_unlock_connector_unknown_location.json')

        request = api_factory.post(url)
        request.data = data
        response = viewset.unlock_connector(request)

        check_ok_result(self, response, http_status=status.HTTP_400_BAD_REQUEST,
                        status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)


class MockResponse:
    def __init__(self, json_data, status_code, headers=None, data=None, reason='Mocked function'):
        self.json_data = json_data
        self._status_code = status_code
        self.reason = reason
        self.headers = headers
        self.data = data

    def json(self):
        return self.json_data

    @property
    def text(self):
        return self.json_data

    def get_status_code(self):
        return self._status_code

    def set_status_code(self, value):
        self._status_code = value

    status_code = property(get_status_code, set_status_code)


class UpdatePartiesTest(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']

    def mocked_token_put(*_args, **kwargs):
        # ic(_args, kwargs)
        headers = {'Authorization': 'Token '
                                    'QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0'
                                    'ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==',
                   'OCPI-from-country-code': 'FI',
                   'OCPI-from-party-id': 'TST',
                   'OCPI-to-country-code': 'FI',
                   'OCPI-to-party-id': '001'}
        return MockResponse(dict(hello=1), 200, headers=kwargs.get('headers') or headers, data=kwargs.get('json'))

    @time_machine.travel(faketime, tick=False)
    def test_update_last_updated(self):
        # Let's try our Token
        # noinspection PyUnresolvedReferences
        token = Token.objects.get(uid='FIMSP-1')
        token.update_last_updated()
        self.assertEqual(token.last_updated, faketime)

        # Then someone else's
        # noinspection PyUnresolvedReferences
        token = Token.objects.get(uid='T1')
        token.update_last_updated()
        self.assertNotEqual(token.last_updated, faketime)

    def test_is_ours(self):
        # Let's try someone elses token
        # noinspection PyUnresolvedReferences
        token = Token.objects.get(uid='T1')
        # from ocpiconnector.ocpi_identities import ocpi_identities
        # ic(token.country_code, token.party_id, ocpi_identities)
        self.assertFalse(token.is_ours(), 'Token ownership is misintepreted')

        # Then our own token
        # noinspection PyUnresolvedReferences
        token = Token.objects.get(uid='FIMSP-1')
        # ic(token.country_code, token.party_id, ocpi_identities)
        self.assertTrue(token.is_ours(), 'Token ownership is misintepreted')

    def test_get_admin_token(self):
        # Get the existing admin token
        token = get_admin_token()
        serializer = TokenSerializer(token)
        expected = {'contract_id': 'INTERNAL',
                    'country_code': 'FI',
                    'issuer': 'FI*MSP',
                    'party_id': 'MSP',
                    'type': 'OTHER',
                    'uid': 'FI*MSP*T*ADMIN*TOKEN',
                    'valid': True}
        self.assertDictEqual(serializer.data, expected, 'Getting the admin token seems not to work')

        # Creating the admin token
        token.delete()
        token = get_admin_token()
        serializer = TokenSerializer(token)
        self.assertDictEqual(serializer.data, expected, 'Creating the admin token seems not to work')

    @time_machine.travel(datetime(2000, 1, 1, 12, 0, tzinfo=pytz.utc), tick=False)
    @patch('ocpi22.tasks.requests.put', side_effect=mocked_token_put)
    def test_update_new_token(self, mock_put: Mock):
        settings.SEND_UPDATES = True
        settings.BACKGROUND_SEND = False
        our_country_code, our_party_id = Token.get_owner_identity().split('*')
        token: Token = Token(country_code=our_country_code, party_id=our_party_id,
                             uid='uid', type='RFID', contract_id='contract',
                             issuer='issuer', whitelist='ALWAYS', last_updated=timezone.now())
        token.save()
        token.send_updates()

        # Let's examine what send_updates() was actually sending

        args, kwargs = mock_put.call_args

        expected_headers = {'Authorization': 'Token '
                                             'QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==',
                            'OCPI-from-country-code': 'FI',
                            'OCPI-from-party-id': 'MSP',  # Tokens are owned by MSP, we should send with MSP identity
                            'OCPI-to-country-code': 'FI',
                            'OCPI-to-party-id': 'HUB',  # The recipient comes from the Credentials in the fixture
                            'content-type': 'application/json'}
        expected_json = {'contract_id': 'CONTRACT',
                         'country_code': 'FI',
                         'issuer': 'issuer',
                         'last_updated': '2000-01-01T12:00:00Z',
                         'party_id': 'MSP',
                         'type': 'RFID',
                         'uid': 'UID',
                         'valid': True,
                         'whitelist': 'ALWAYS'}

        self.assertEqual(kwargs['url'], 'http://localhost:8001/ocpi/cpo/2.2/tokens',
                         'Expected to send the update to another address')
        assert (isinstance(expected_headers, dict))
        assert (isinstance(kwargs['headers'], dict))
        self.assertDictEqual(kwargs['headers'], expected_headers,
                             'Headers differ from expected')
        self.assertDictEqual(kwargs['json'], expected_json,
                             'JSON content differs from expected')


def check_ok_result(testcase: TestCase, response, status_code: int = 1000, http_status: int = 200,
                    command_result: str = None) -> None:
    testcase.assertEqual(response.data.get('status_code'), status_code,
                         msg=f'Expecting OCPI status code {status_code}')
    testcase.assertEqual(response.status_code, http_status,
                         msg=f'Expecting HTTP status code {http_status}')
    if command_result:
        testcase.assertEqual(response.data.get('data').get('result'), command_result,
                             msg=f'Expecting the result "{command_result}"')


fake_token = '1234567890'


class TestCredentials(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']

    def mocked_credentials_get(url, *_args, **_kwargs):
        assert isinstance(url, str)
        # ic(url, _args, _kwargs)

        response_data = {
            'http://localhost/versions': [{'url': 'http://localhost/ocpi/cpo/2.2/', 'version': '2.2'}],
            'http://localhost/ocpi/cpo/2.2/': ocpi_endpoints_response,
            'http://localhost/ocpi/cpo/2.2/credentials': ocpi_endpoints_response,
        }
        return MockResponse(response_data[url], 200)

    def mocked_credentials_post(url, *_args, **_kwargs):
        # ic(_args, _kwargs)
        response = {
            "status_code": 1000, "status_message": "", "timestamp": timezone.now(),
            "data": {"token": fake_token + fake_token,
                     "url": "http://localhost:8000/ocpi/versions/",
                     "roles":
                         [
                             {
                                 "country_code": "FI", "party_id": "HUB", "role": "HUB",
                                 "business_details": {"name": "ChargerHub.EU"}
                             }
                         ]
                     }
        }

        return MockResponse(response, 200)

    def mocked_credentials_delete(url, *_args, **_kwargs):
        # ic(_args, _kwargs)
        response = {
            "status_code": 1000, "status_message": "", "timestamp": timezone.now(),
            "headers": {"fakeheader": 1},
            "data": {"token": fake_token + fake_token,
                     "url": "http://localhost:8000/ocpi/versions/",
                     "roles":
                         [
                             {
                                 "country_code": "FI", "party_id": "HUB", "role": "HUB",
                                 "business_details": {"name": "ChargerHub.EU"}
                             }
                         ]
                     }
        }

        return MockResponse(response, 200)

    @time_machine.travel(faketime, tick=False)
    @patch('ocpiconnector.management.commands.exchange_credentials.generate_random_token', side_effect=[fake_token])
    @patch('ocpiconnector.management.commands.exchange_credentials.requests.post', side_effect=mocked_credentials_post)
    @patch('ocpiconnector.management.commands.exchange_credentials.requests.get', side_effect=mocked_credentials_get)
    def test_exchange(self, mock_get: Mock, mock_post: Mock, _mock_generate_random_token):
        command = exchange_credentials.Command()
        _result = command.handle(token_a='918273', versions_endpoint_url='http://localhost/versions')

        # Let's examine what was actually sent
        args, kwargs = mock_get.call_args

        expected_headers = {'Authorization': 'Token OTE4Mjcz'}

        self.assertDictEqual(kwargs['headers'], expected_headers,
                             'Headers differ from expected')

        args, kwargs = mock_post.call_args

        expected_data = {'roles': [{'business_details': {'name': 'ChargerHub.EU', 'website': ''},
                                    'country_code': 'FI',
                                    'party_id': 'CPO',
                                    'role': 'CPO'},
                                   {'business_details': {'name': 'ChargerHub.EU', 'website': ''},
                                    'country_code': 'FI',
                                    'party_id': 'MSP',
                                    'role': 'EMSP'}],
                         'token': fake_token,
                         'url': 'http://localhost:8000/ocpi/versions/'}

        json_data = kwargs['json']
        # ic(json_data)
        # ic(kwargs['headers'])
        self.assertDictEqual(json_data, expected_data, 'Credentials endpoint gives an unexpected response')

    @time_machine.travel(faketime, tick=False)
    @patch('ocpiconnector.management.commands.exchange_credentials.requests.delete',
           side_effect=mocked_credentials_delete)
    def test_delete(self, mock_delete: Mock):
        # noinspection PyUnresolvedReferences
        credentials = Credentials.objects.get(pk=2)
        self.assertTrue(credentials.roles.count())
        self.assertTrue(credentials.endpoints.count())
        # ic(credentials)

        credentials.delete()

        # Let's examine what was actually sent
        args, kwargs = mock_delete.call_args

        # ic(args, kwargs)
        expected_headers = {'Authorization': 'Token '
                                             'QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==',
                            'OCPI-from-country-code': 'FI',
                            'OCPI-from-party-id': 'CPO',
                            'OCPI-to-country-code': 'FI',
                            'OCPI-to-party-id': 'CP1',
                            'content-type': 'application/json'}
        self.assertDictEqual(kwargs.get('headers'), expected_headers,
                             f'Headers differ from expected')


class TestObjectPull(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']

    def mocked_object_get(url, *_args, **kwargs):
        # ic(url, _args, kwargs)
        # noinspection PyUnresolvedReferences
        credentials = Credentials.objects.get(pk=2)
        headers = kwargs['headers']
        # Let's swap the other token and receive this request as if it comes from outside
        headers['HTTP_AUTHORIZATION'] = f'Token {credentials.ours_base64()}'
        result = client.get(url, **headers)
        json_text = result.content.decode('utf-8')
        assert 'DOCTYPE' not in json_text, f"URL {url} is returning HTML, when excepting JSON"
        content = json.loads(json_text)
        response_headers = dict(result.headers)
        # ic(url, response_headers)
        # ic(content)
        # ic(content, expected_get_responses[url])
        assert content == expected_get_responses[url], f"Expecting a different result for {url}."
        assert response_headers == expected_get_headers[url], f"Expecting different headers for {url}."
        return result

    @time_machine.travel(faketime, tick=False)
    @patch('ocpiconnector.management.commands.exchange_credentials.requests.get', side_effect=mocked_object_get)
    def test_pull(self, _mock_get: Mock):
        settings.SEND_UPDATES = True
        settings.BACKGROUND_SEND = False

        # noinspection PyUnresolvedReferences
        credentials = Credentials.objects.get(pk=2)
        schedule_full_update(credentials, countdown=0, limit=3)

        # Content is verified in mocked_object_get


class CredentialsTest(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']

    def test_cached_partylist(self):
        location_url = f"http://localhost:8001{reverse('location-list')}"
        token_url = f"http://localhost:8001{reverse('token-list')}"
        tariff_url = f"http://localhost:8001{reverse('tariff-list')}"
        token = 'QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw=='

        testcases = (
            (Location, [(location_url, token, 'FI', 'MSP'),
                        (location_url, token, 'FI', 'NAP'),
                        (location_url, token, 'FI', 'HUB')]),
            (Token, [(token_url, token, 'FI', 'CP1'),
                     (token_url, token, 'FI', 'HUB')]),
            (Tariff, [(tariff_url, token, 'FI', 'MSP'),
                      (tariff_url, token, 'FI', 'NAP'),
                      (tariff_url, token, 'FI', 'HUB')]),
        )
        counter = 0
        ocpi_object: OcpiModule
        for ocpi_object, endpoints_result in testcases:
            roles = ocpi_object.send_updates_to
            self.assertIsInstance(
                roles, tuple,
                f'{ocpi_object} needs to have a send_updates_to specified as a tuple, so that caching works.'
            )

            cache_info = find_endpoints_by_roles.cache_info()
            self.assertEqual((cache_info.hits, cache_info.misses), (counter, counter),
                             f"Cache doesn't work as expected for {ocpi_object}")
            # Check that the cache is in use
            find_endpoints_by_roles(roles, ocpi_object.ocpi_module_name)
            cache_info = find_endpoints_by_roles.cache_info()
            self.assertEqual((cache_info.hits, cache_info.misses), (counter, counter + 1),
                             f"Cache doesn't work as expected for {ocpi_object}")

            endpoints = find_endpoints_by_roles(roles, ocpi_object.ocpi_module_name)
            cache_info = find_endpoints_by_roles.cache_info()
            self.assertEqual((cache_info.hits, cache_info.misses), (counter + 1, counter + 1),
                             f"Cache doesn't work as expected for {ocpi_object}")
            counter += 1

            self.assertEqual(
                endpoints, endpoints_result,
                f'Cannot find the right endpoints for {roles} to send updates to'
            )

        # Check that changes to Credentials reset the endpoint cache
        # noinspection PyUnresolvedReferences
        self.assertGreater(find_endpoints_by_roles.cache_info().currsize, 0)
        # noinspection PyUnresolvedReferences
        c: Credentials = Credentials.objects.get(pk=2)
        c.update_last_updated()
        c.atomic_post_save()
        self.assertFalse(find_endpoints_by_roles.cache_info().currsize,
                         'There should be nothing in endpoint cache after changing a Credentials')


routed_response_text = 'Hello from the other side'


class TestRouting(TestCase):
    fixtures = ['ocpi22/data/test-database-hub.json']

    def test_middleware(self):
        # Check that the middleware stack works
        for url in ('/', '/admin/login/', '/ocpi/versions/'):
            response = self.client.get(url)
            self.assertTrue(b'Headers missing: OCPI-to-country-code' not in response.content,
                            'Looks like using Admin UI is not possible due to over eager OCPI routing middleware')
            self.assertEqual(response.status_code, 200, 'Middleware may not work together properly')

    def test_find_route(self):
        try:
            self.assertTrue(hasattr(find_route, 'cache_info'), "find_route() should be cached")
            find_route.cache_clear()
            route: Route = find_route(Party('fi', 'msp'), OcpiModuleEnum.LOCATIONS)

            # Does caching work?
            find_route(Party('fi', 'msp'), OcpiModuleEnum.LOCATIONS)  # These should be acceptable in lower case
            self.assertEqual(find_route.cache_info().hits, 1, "find_route() should be cached")

            self.assertDictEqual(
                asdict(route),
                {'alive': True,
                 'credentials_id': 2,
                 'direct': True,
                 'identifier': OcpiModuleEnum.LOCATIONS.value,
                 'token_base64': 'dGhlaXJzLTI=',
                 'url': 'http://localhost:8001/ocpi/nap/2.2/locations'},
                'Expected route not found')
        except AttributeError as e:
            self.fail(f"find_route() is probably not cached: {e}")

    def test_find_hub_route(self):
        # Route to an unknown party
        route: Route = find_route(Party('no', 'exi'), OcpiModuleEnum.LOCATIONS)
        self.assertTrue(route.through_hub, 'Seems that a hub route is not found')
        self.assertDictEqual(
            asdict(route),
            {'alive': True,
             'credentials_id': 3,
             'direct': False,
             'identifier': 'locations',
             'token_base64': 'dGhlaXJzLTM=',
             'url': 'http://localhost:8001/ocpi/hub/2.2/locations'},
            'Expecting a different route through hub')

    def mocked_request(*_args, **kwargs):
        # ic()
        # ic(_args, kwargs)
        return MockResponse(
            json.dumps(dict(message=routed_response_text)), 200,
            headers=kwargs.get('headers'),
            data=kwargs.get('json')
        )

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.middleware.is_our_identifier', return_value=False)
    @patch('ocpi22.routing.requests.request', side_effect=mocked_request)
    def test_message_routing(self, mock_request: Mock, mock_is_our_identifier: Mock):
        # Let's fake we are FI*HUB, need to clear cache first not to get old info
        is_our_identifier.cache_clear()
        setattr(self, 'get_response_called', False)

        url = reverse('commands-start-session')

        data = {'message': 'This is a message routing test'}
        # noinspection PyUnresolvedReferences
        credentials = Credentials.objects.get(pk=2)
        sender = Party('FI', 'NAP')

        def fake_get_response(_request):
            # We want to know when this gets called
            self.get_response_called = True
            return HttpResponse('Everything is good', status=status.HTTP_200_OK)

        test_cases = (
            dict(label='All good', result=200),
            dict(label='Missing token', token='', result=401),
            dict(label='Unknown recipient', party=Party('UN', 'KNO'), result=404),
            dict(label='Missing recipient', party=Party('', ''), result=200),  # This should be ok, or no Admin UI
            dict(label='Hub as recipient', party=Party('FI', 'HUB'), result=200, routing=False, this_is_us=True),
        )

        for testcase in test_cases:
            # print(f'Testing `{testcase.get("label")}`')
            mock_request.reset_mock()
            routing = testcase.get('routing', True)
            mock_is_our_identifier.return_value = testcase.get('this_is_us')
            to = testcase.get('party')
            if to is None:  # Let empty Party through
                to = Party('FI', 'CPO')
            headers = make_headers(testcase.get('token', credentials.ours_base64()), to, sender)
            request = api_factory.post(url, **headers)
            request.data = json.dumps(data)
            request.credentials = credentials

            middleware = OCPIHubMiddleware(fake_get_response)
            response = middleware(request)
            self.assertEqual(response.status_code, testcase.get('result'),
                             f'Unexpected result for case "{testcase.get("label")}"')

            if response.status_code < 300:
                # Check that hub middleware passes the request forward only when routing has not been requested
                self.assertTrue(routing or self.get_response_called,
                                'Seems that routing does not happen when it should, or happens when it should not')
                self.get_response_called = False

                if testcase.get('routing'):
                    # Let's check that routing has been done
                    args, kwargs = mock_request.call_args
                    # ic(args, kwargs)
                    self.assertDictEqual(
                        kwargs,
                        {'data': '{"message": "This is a message routing test"}',
                         'headers': {'Authorization': 'Token dGhlaXJzLTk=',
                                     'OCPI-from-country-code': sender.country_code,
                                     'OCPI-from-party-id': sender.party_id,
                                     'OCPI-to-country-code': to.country_code,
                                     'OCPI-to-party-id': to.party_id,
                                     'content-type': 'application/json'},
                         'method': 'POST',
                         'url': 'http://localhost:9002/ocpi/cpo-fi/2.2/commands/START_SESSION'},
                        f'The routed hub message is not as expected'
                    )
                    self.assertJSONEqual(response.content, {'message': 'Hello from the other side'},
                                         'Hub routed message response is not as expected')


def make_json_response(data, status_code=200) -> Response:
    response = Response()
    response.status_code = status_code
    response.encoding = 'UTF-8'
    response._content = json.dumps(data).encode('UTF-8')
    return response


class TestSession(TestCase):
    fixtures = ['ocpi22/data/test-database-sessions.json']
    maxDiff = None

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.cpo.util.redis_store.get',
           side_effect=lambda x: {'callback-start_transaction_url': 'http://localhost/start/{evse_id}/'}.get(x))
    @patch('ocpi22.sessions.util.generate_session_uid',
           side_effect=['FAKE-SESSION-UID-1', 'FAKE-SESSION-UID-2'])
    @patch('ocpi22.tokens.auth.ocpi_post', side_effect=[make_json_response(accept_authorization)])
    def test_update_session(self,
                            _ocpi_post_mock: Mock,
                            _generate_session_uid_mock: Mock,
                            _get_parameter_mock: Mock):
        evse = Evse.objects.all()[0]
        location = evse.location
        uid = '12345'

        session = create_session(location.uid, evse.uid, 1, "T1", billed_to='FI*MSP', uid=uid)
        self.assertTrue(bool(session))
        # ic(session)

        test_cases = (
            ('session_patch_example_charging_period', 200, 0.8, 1, None),
            ('session_patch_example_charging_period_update_1', 200, 1.0, 1, ExpectedSessionUpdateResults.update1),
            ('session_patch_example_charging_period_update_2', 200, 1.1, 2, ExpectedSessionUpdateResults.update2),
        )

        args = (session.country_code, session.party_id, session.uid)
        session_url = reverse('session-by-id', args=args)
        # ic(session_url)

        request = api_factory.patch(session_url)
        request.user = AnonymousUser
        request.credentials = Credentials.objects.get(pk=2)

        for filename, status_code, cost, charging_period_count, expected_dict in test_cases:
            data = load_example(f'data/examples/{filename}.json')
            request.data = data
            response = SessionViewSet().patch(request, *args)

            self.assertEqual(response.status_code, status_code,
                             f'Expecting status code {status_code}')

            session = Session.objects.get(uid=uid)
            self.assertEqual(session.total_cost_excl_vat, cost,
                             f'Session price was not changed to {cost}')

            self.assertEqual(session.chargingperiods.count(), charging_period_count,
                             f'Expecting {charging_period_count} ChargingPeriods')

            if expected_dict:
                session_data = SessionSerializer(instance=session).data
                # ic(session_data)

                self.assertDictEqual(session_data, expected_dict,
                                     'The charging session content differs from expected')


class TestCpoApi(TestCase):
    fixtures = ['ocpi22/data/test-database-cpo-api.json']
    maxDiff = None

    @time_machine.travel(faketime, tick=False)
    def test_status_change(self):

        evse = Evse.objects.get(uid='HELSINKI-3')
        self.assertEqual(evse.status, 'AVAILABLE')

        status_change_url = reverse('chargepoint-status-change')
        cpo_viewset = ChargePointViewSet()
        cpo_request = api_factory.post(status_change_url)
        testcases = (
            dict(
                request=dict(
                    evse_id='HELSINKI-3',
                    status='PREPARING',
                ),
                response={'evse': 'HELSINKI-3',
                          'ocpi_status': 'CHARGING',
                          'ocpp_status': 'PREPARING',
                          'status_text': 'EVSE status has been changed'},
                status_code=200,
                evse_status='CHARGING'
            ),
            dict(
                request=dict(
                    evse_id='NON-EXISTENT-EVSE',
                    status='AVAILABLE',
                ),
                response={'status': 'EVSE with ID NON-EXISTENT-EVSE does not exist in the OCPI '
                                    'Connector database for party FI*CPO'},
                status_code=404
            ),
        )

        for case in testcases:
            cpo_request.data = case.get('request')
            cpo_response = cpo_viewset.status_change(cpo_request)
            # ic(cpo_response, cpo_response.data)

            self.assertEqual(cpo_response.status_code, case.get('status_code'),
                             'Status change should succeed')
            self.assertDictEqual(cpo_response.data, case.get('response'),
                                 f'Case request {case.get("request")}, response {case.get("response")}')
            if cpo_response.status_code != 404:
                evse = Evse.objects.get(uid=case.get('request').get('evse_id'))
                self.assertEqual(evse.status, case.get('evse_status'))

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.models.session.OcpiModule.send_updates')
    @patch('ocpi22.cpo.util.redis_store.get',
           side_effect=lambda x: {'callback-start_transaction_url': 'http://localhost/start/{evse_id}/'}.get(x))
    @patch('ocpi22.sessions.util.generate_session_uid',
           side_effect=['FAKE-SESSION-UID-1', 'FAKE-SESSION-UID-2'])
    @patch('ocpi22.tokens.auth.ocpi_post', side_effect=[make_json_response(accept_authorization)])
    def test_rfid_charging_flow(self,
                                ocpi_post_mock: Mock,
                                _generate_session_uid_mock: Mock,
                                _get_parameter_mock: Mock,
                                send_updates_mock: Mock):

        evse = Evse.objects.get(uid='HELSINKI-3')
        self.assertEqual(evse.status, 'AVAILABLE')

        start_transaction_url = reverse('chargepoint-start-transaction')
        cpo_viewset = ChargePointViewSet()
        cpo_request = api_factory.post(start_transaction_url)
        cpo_request.data = {
            "evse_id": "HELSINKI-3",
            "connector_id": "1",
            "token_id": "EKI1",
            "session_id": "MY-SESSION",
            "start_kwh": 120
        }
        cpo_response = cpo_viewset.start_transaction(cpo_request)
        # ic(cpo_response.data)
        self.assertEqual(cpo_response.status_code, 200, 'Start session should succeed')

        testcases = (
            dict(
                request=dict(
                    session_id='MY-SESSION',
                    kwh=123.45,
                    soc=42,
                ),
                expected_response={'now_kwh': 123.45,
                                   'power': None,
                                   'price': '2,14€',
                                   'session_id': 'MY-SESSION',
                                   'soc': 42.0,
                                   'start_kwh': 120.0,
                                   'status_text': 'Session updated',
                                   'total_kwh': 3.45},
                session_data={'auth_method': 'AUTH_REQUEST',
                              'authorization_reference': 'FAKE-AUTHORIZATION-REFERENCE',
                              'cdr_token': OrderedDict([('uid', 'EKI1'),
                                                        ('type', 'RFID'),
                                                        ('contract_id', 'DE8ACC12E46L89')]),
                              'charging_periods': [OrderedDict([('start_date_time', '2000-01-01T12:00:00Z'),
                                                                ('tariff', 'EKI1'),
                                                                ('dimensions',
                                                                 [OrderedDict([('type', 'ENERGY'),
                                                                               ('volume', '3.4500')]),
                                                                  OrderedDict([('type', 'STATE_OF_CHARGE'),
                                                                               ('volume', '42.0000')])])])],
                              'connector_id': '1',
                              'country_code': 'FI',
                              'currency': 'EUR',
                              'evse_uid': 'HELSINKI-3',
                              'kwh': 3.45,
                              'location_id': 'HELSINKI-1',
                              'party_id': 'CPO',
                              'start_date_time': '2000-01-01T12:00:00Z',
                              'status': 'ACTIVE',
                              'uid': 'MY-SESSION'},
                expected_update_data={'charging_periods': [OrderedDict(
                    [('start_date_time', '2000-01-01T12:00:00Z'), ('tariff', 'EKI1'), ('dimensions', [
                        OrderedDict([('type', 'ENERGY'), ('volume', '3.4500')]),
                        OrderedDict([('type', 'STATE_OF_CHARGE'), ('volume', '42.0000')])])])],
                    'kwh': 3.45,
                    'last_updated': '2000-01-01T12:00:00Z',
                    'total_cost': {'excl_vat': 1.73, 'incl_vat': 2.14}},
                evse_status='CHARGING'
            ),
            dict(
                request=dict(
                    session_id='MY-SESSION',
                    kwh=153.45,
                    soc=80,
                ),
                expected_response={'now_kwh': 153.45,
                                   'power': None,
                                   'price': '20,74€',
                                   'session_id': 'MY-SESSION',
                                   'soc': 80.0,
                                   'start_kwh': 120.0,
                                   'status_text': 'Session updated',
                                   'total_kwh': 33.45},
                session_data={'auth_method': 'AUTH_REQUEST',
                              'authorization_reference': 'FAKE-AUTHORIZATION-REFERENCE',
                              'cdr_token': OrderedDict([('uid', 'EKI1'),
                                                        ('type', 'RFID'),
                                                        ('contract_id', 'DE8ACC12E46L89')]),
                              'charging_periods': [OrderedDict([('start_date_time', '2000-01-01T12:00:00Z'),
                                                                ('tariff', 'EKI1'),
                                                                ('dimensions',
                                                                 [OrderedDict([('type', 'ENERGY'),
                                                                               ('volume', '33.4500')]),
                                                                  OrderedDict([('type', 'STATE_OF_CHARGE'),
                                                                               ('volume', '80.0000')])])])],
                              'connector_id': '1',
                              'country_code': 'FI',
                              'currency': 'EUR',
                              'evse_uid': 'HELSINKI-3',
                              'kwh': 33.45,
                              'location_id': 'HELSINKI-1',
                              'party_id': 'CPO',
                              'start_date_time': '2000-01-01T12:00:00Z',
                              'status': 'ACTIVE',
                              'uid': 'MY-SESSION'},
                evse_status='CHARGING'
            ),
            dict(
                request=dict(
                    session_id='NON-EXISTENT-SESSION',
                    kwh=123.45,
                ),
                expected_response={'status': 'Session matching query does not exist.'},
                status_code=404
            ),
        )

        for case in testcases:
            cpo_response = self.meter_values(case.get('request'))
            # ic(cpo_response, cpo_response.data)

            args, kwargs = send_updates_mock.call_args

            self.assertEqual(kwargs.get('method'), 'patch', 'PATCH should be used for Session updates')
            expected_update_data = case.get('expected_update_data')
            if expected_update_data:
                update_data = args[0]
                expected_serializer = SessionSerializer(data=update_data, partial=True)
                self.assertTrue(expected_serializer.is_valid(),
                                f'The Session update data does not comply with schema: {expected_serializer.errors}')
                self.assertTrue(update_data.get('charging_periods'),
                                'Charging periods missing from Session update')
                self.assertDictEqual(update_data, expected_update_data,
                                     f'Sending Session update differs from expected')

            expected_status = case.get('status_code', 200)
            self.assertEqual(cpo_response.status_code, expected_status,
                             f'Expecting HTTP status {expected_status} for {case.get("request")}')
            self.assertDictEqual(cpo_response.data, case.get('expected_response'),
                                 f'Case request {case.get("request")}, response {cpo_response.data}')
            expected_session_data = case.get('session_data')
            if expected_session_data:
                session = Session.objects.get(uid=cpo_request.data.get('session_id'))
                session_data = SessionSerializer(instance=session).data
                self.assertDictEqual(session_data, expected_session_data,
                                     'Session data differs')

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://fakehost/stop/{evse_id}/',
           }.get(x))
    @patch('ocpi22.util.redis_store.set', return_value=True)
    @patch('ocpi22.sessions.util.generate_session_uid',
           side_effect=['FAKE-SESSION-UID-1', 'FAKE-SESSION-UID-2'])
    @patch('ocpi22.commands.commands.requests.post')
    def test_adhoc_token(self,
                         requests_post_mock: Mock,
                         _generate_session_uid_mock: Mock,
                         _set_parameter_mock: Mock,
                         _get_parameter_mock: Mock):
        url = reverse('commands-start-session')
        viewset = CommandsViewSet()

        # Load up the test message and send it
        data = load_example(f'data/examples/command_start_session_adhoc.json')

        billed_party = Party('FI', 'EON')
        headers = make_headers('', Party('FI', 'CPO'), billed_party)
        request = api_factory.post(url, **headers)
        request.data = data

        self.assertFalse(Session.objects.all().exists(),
                         'Please make sure there are no Sessions at the start of this test')

        # Let's pretend to be the CPO and all is good
        requests_post_mock.return_value = make_json_response(dict(result='ACCEPTED'))

        response = viewset.start_session(request)

        # Let's guess the new Session
        session = Session.objects.all().first()
        self.assertEqual(session.billed_to, str(billed_party), 'Billed party appears not to be stored properly')

        args, kwargs = requests_post_mock.call_args
        # ic(args, kwargs)

        self.assertEqual(response.status_code, 200, 'Remote Command start_session was expected to succeed')
        self.assertEqual(kwargs.get('url'), 'http://fakehost/start/HELSINKI-3/',
                         'CPO start transaction URL differs from expected')
        self.assertDictEqual(
            kwargs.get('json'),
            {'auth_method': 'COMMAND',
             'authorization_reference': 'FI*001-AUTH-REFERENCE',
             'billed_to': 'FI*EON',
             'connector_id': None,
             'evse_id': 'HELSINKI-3',
             'response_url': 'http://testserver/api/cpo/v2/chargepoint/remote_command_result/FI*001-AUTH-REFERENCE/',
             'token_id': 'SOME-ADHOC-TOKEN',
             'token_type': 'AD_HOC_USER'}
        )

        session = Session.objects.get(status='PENDING')
        self.assertEqual(session.evse.uid, 'HELSINKI-3', "Session UID doesn't match expectation")

        #
        # Check that authorization based on Command from eMSP stands valid
        #

        data = dict(
            evse_id='HELSINKI-3',
            token_id='SOME-ADHOC-TOKEN'
        )
        cpo_response = self.authorize(data)
        # ic(cpo_response, cpo_response.data)

        self.assertEqual(cpo_response.status_code, 200,
                         'Token should be authorized')
        self.assertDictEqual(cpo_response.data,
                             {'authorization_method': 'COMMAND',
                              'authorization_reference': 'FI*001-AUTH-REFERENCE',
                              'billed_to': 'FI*CPO',
                              'evse_id': 'HELSINKI-3',
                              'status_text': 'Token authorized for charging',
                              'token_id': 'SOME-ADHOC-TOKEN',
                              'token_type': 'AD_HOC_USER'}
                             )

        #
        # Start session based on authorization from eMSP Command
        #

        data = dict(
            evse_id='HELSINKI-3',
            token_id='SOME-ADHOC-TOKEN',
            session_id='MY-SESSION',
            connector_id='1',
        )
        cpo_response = self.start_transaction(data)

        self.assertDictEqual(
            cpo_response.data,
            {'session': {'auth_method': 'COMMAND',
                         'authorization_reference': 'FI*001-AUTH-REFERENCE',
                         'billed_to': 'FI*EON',
                         'currency': 'EUR',
                         'evse_uid': 'HELSINKI-3',
                         'location_id': 'HELSINKI-1',
                         'connector_id': '1',
                         'session_id': 'MY-SESSION',
                         'start_date_time': '2000-01-01T12:00:00',
                         'start_kwh': 0.0,
                         'status': 'ACTIVE',
                         'token': OrderedDict([('token_id', 'SOME-ADHOC-TOKEN'),
                                               ('type', 'AD_HOC_USER'),
                                               ('contract_id', 'INTERNAL')])},
             'status_text': 'Session started'}
        )

        #
        # Check that the AD_HOC_USER token expires after 15 minutes
        #

        with time_machine.travel(faketime + timedelta(minutes=16), tick=False):
            data = dict(
                evse_id='HELSINKI-3',
                token_id='SOME-ADHOC-TOKEN'
            )

            _get_authorization_from_sessions.cache_clear()
            _authorize_token.cache_clear()
            authorize_token.cache_clear()

            cpo_response = self.authorize(data)
            self.assertEqual(cpo_response.status_code, 401,
                             'Token should NOT be authorized')
            self.assertDictEqual(cpo_response.data,
                                 {'status_text': 'Token is (temporarily) not valid',
                                  'token_id': 'SOME-ADHOC-TOKEN'}
                                 )

        #
        # CPO gives a broken response, we should return HTTP 503 to eMSP
        #

        response = make_json_response(dict(broken_response='APPLES_AND_ORANGES'))
        requests_post_mock.return_value = response

        response = viewset.start_session(request)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE,
                         'JSON decode errors should return HTTP 503')

        # Check that authorizations are cached
        self.assertTrue(hasattr(_get_authorization_from_sessions, 'cache_clear'),
                        f'get_authorization_from_sessions should be cached for 1 minute')
        self.assertTrue(hasattr(_authorize_token, 'cache_clear'),
                        f'_authorize_token should be cached for 15 minutes')
        self.assertTrue(hasattr(authorize_token, 'cache_clear'),
                        f'authorize_token should be cached for 15 minutes')

        # Todo: Send CPO API authorize for AD_HOC_USER with and after 15 min has expired

        #
        # Try updating meter values without a tariff specified
        #

        data = dict(
            session_id='MY-SESSION',
            kwh=123.45,
            soc=42,
            power=150
        )
        cpo_response = self.meter_values(data)
        self.assertEqual(cpo_response.status_code, status.HTTP_417_EXPECTATION_FAILED)

        #
        # Update meter values with a tariff
        #

        session = Session.objects.get(uid='MY-SESSION')
        session.connector.tariff_ids.set([9])
        session.save()

        response = self.meter_values(data)
        # ic(response, response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.data,
                             {'now_kwh': 123.45,
                              'power': 150.0,
                              'price': '76,54€',
                              'session_id': 'MY-SESSION',
                              'soc': 42.0,
                              'start_kwh': 0.0,
                              'status_text': 'Session updated',
                              'total_kwh': 123.45}
                             )

    def meter_values(self, data):
        cpo_request = api_factory.post(reverse('chargepoint-meter-values'))
        cpo_request.data = data
        return ChargePointViewSet().meter_values(cpo_request)

    def start_transaction(self, data):
        start_url = reverse('chargepoint-start-transaction')
        start_request = api_factory.post(start_url)
        start_request.data = data
        return ChargePointViewSet().start_transaction(start_request)

    def authorize(self, data):
        authorize_url = reverse('chargepoint-authorize')
        cpo_request = api_factory.post(authorize_url)
        cpo_request.data = data
        return ChargePointViewSet().authorize(cpo_request)

# Todo: Hub to relay Evse PATCH to everybody as PATCH
