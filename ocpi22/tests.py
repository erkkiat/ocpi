import doctest
import json
import os
from typing import Optional
from urllib.parse import urljoin

from rest_framework.exceptions import NotAuthenticated

import ocpi22.logging as logging
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field

from datetime import timedelta, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytz
import redis.exceptions
import time_machine
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase, Client

# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30} // [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-
#  Za-z0-9\*]{0,30}
# Todo: Tariff_id: Regular Expression: [A-Z]{2}[A-Za-z0-9]{3}[T][A-Z0-9][A-Z0-9\*]{0,29}
# Todo: evse_id Regular Expression: [A-Z]{2}\*[A-Za-z0-9]{3}\*[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}
#                                   [A-Z]{2}[A-Za-z0-9]{3}[E][A-Za-z0-9][A-Za-z0-9\*]{0,30}   ????
from requests import Response
from rest_framework import status

from ocpi22.locations.serializers import LocationSerializer
from ocpi22.msp.account import Account
from ocpi22.ocpi.auth import get_credentialsrole, check_auth_token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.partners import invalidate_partner_cache
from ocpiconnector.testutil import compare_dicts_recursively, OCPIAPIRequestFactory
from ocpiconnector.util import recursive_sort_dict
from settlement.views import InvoiceReportViews
from util import reverse

from cars import test_data
from ocpi22.msp.api import MspRoamingViewSet
from ocpi22.msp.models import Authorization
from ocpi22.msp.user import UserViewSet
from ocpi22.ocpi.api import TariffViewSet, CdrViewSet, TokenViewSet, SessionViewSet
from ocpi22.ocpi.serializers import TokenSerializer, TariffSerializer, CdrSerializer, SessionSerializer
from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum, MessageTexts, TokenType
from ocpi22.commands.commands import CommandsViewSet
from ocpi22.commands.serializers import CommandResponse
from ocpi22.cpo.api import ChargePointViewSet
from ocpi22.locations.location import LocationViewSet, EvseViewSet
from ocpi22.middleware import OCPIHubMiddleware
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.credentials.util import find_endpoints_by_roles
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
    accept_authorization, ExpectedSessionUpdateResults, CdrMessages, StopTransactionResponses, SessionData, \
    RfidTestData, accept_authorization_msp, SessionCommandsData
from ocpi22.tokens.auth import authorize_token, _get_authorization_from_sessions, _authorize_token, TokenAuthorization
from ocpi22.tokens.util import get_admin_token
from ocpi22.util import is_our_identifier
from ocpiconnector.management.commands import exchange_credentials
from ocpi22.test_data import expected_get_responses
from ocpiconnector.ocpi_identities import Party, get_our_party, create_credentialsrole
from settlement.calculate import create_invoice

global ic
faketime = datetime(2022, 1, 1, 12, 0)
client = Client()
dirname = os.path.dirname(os.path.abspath(__file__))
api_factory = OCPIAPIRequestFactory()


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.ocpi.api'))
    tests.addTests(doctest.DocTestSuite('ocpi22.ocpi.parse'))
    tests.addTests(doctest.DocTestSuite('ocpi22.util'))
    tests.addTests(doctest.DocTestSuite('ocpi22.choices'))
    tests.addTests(doctest.DocTestSuite('ocpi22.ocpi.util'))
    tests.addTests(doctest.DocTestSuite('ocpi22.locations.location'))
    tests.addTests(doctest.DocTestSuite('ocpi22.locations.serializers'))
    tests.addTests(doctest.DocTestSuite('ocpi22.commands.commands'))
    tests.addTests(doctest.DocTestSuite('ocpi22.commands.serializers'))
    tests.addTests(doctest.DocTestSuite('ocpi22.models.dynamic_price'))
    tests.addTests(doctest.DocTestSuite('ocpi22.tasks'))
    tests.addTests(doctest.DocTestSuite('ocpi22.routing'))
    tests.addTests(doctest.DocTestSuite('ocpi22.models.tariff'))
    tests.addTests(doctest.DocTestSuite('ocpiconnector.management.commands.exchange_credentials'))
    tests.addTests(doctest.DocTestSuite('ocpiconnector.settings'))
    tests.addTests(doctest.DocTestSuite('ocpiconnector.util'))
    tests.addTests(doctest.DocTestSuite('util'))
    tests.addTests(doctest.DocTestSuite('ocpiconnector.ocpi_identities'))
    return tests


def make_json_response(data, status_code=200) -> Response:
    response = Response()
    response.status_code = status_code
    response.encoding = 'UTF-8'
    response.json = lambda: data
    data_str = json.dumps(data).encode('UTF-8')
    response._content = data_str
    return response


@dataclass(eq=True, frozen=True)
class FakeResponse:
    status_code: int
    data: dict
    reason: str = field(default='Mocked response')

    def json(self):
        return self.data

    @property
    def text(self):
        return self.data


def load_example(filename: str) -> dict:
    with open(os.path.join(dirname, filename)) as file:
        return json.load(file)


def create_tariff(*_args, **kwargs) -> Tariff:
    params = dict(
        currency='EUR'
    )
    params.update(kwargs)
    tariff = Tariff.objects.create(**params)
    tariff_element = TariffElement.objects.create(tariff=tariff)
    PriceComponent.objects.create(type='FLAT', price=1.0, step_size=1, tariff_element=tariff_element)
    return tariff


def make_sure_no_min_price(tariff: Tariff) -> bool:
    return not tariff.min_price_excl_vat and not tariff.min_price_incl_vat


class ApiPutTests(TestCase):
    fixtures = ['ocpi22/data/initial.json']
    location_index = 1
    maxDiff = None

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

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.location = self.create_location()
        self.credentials = Credentials.objects.create(token_a='TOKEN_A', ours='OURS', theirs='THEIRS')
        self.credentialsrole = create_credentialsrole(Party(self.location.country_code, self.location.party_id),
                                                      business_name='Test Business', website='http://example.com',
                                                      role=OcpiRolesEnum.CPO, credentials=self.credentials)
        self.country_code = self.location.country_code
        self.party_id = self.location.party_id

    def test_evse_with_same_id(self):
        # Create two locations with the same Evse IDs
        _location1 = self.create_location()
        _location2 = self.create_location()

    def test_evse_format(self):
        loc = self.create_location()
        evse = loc.evses.all()[0]
        url = reverse('location-by-evse-id',
                      args=[loc.country_code, loc.party_id, loc.uid, evse.uid])

        request = api_factory.get(url)
        request.version = '2.2.1'
        request.accepted_media_type = ['text/html']  # To get the detail_url in the response
        viewset = EvseViewSet()
        response = viewset.get(request, loc.country_code, loc.party_id, loc.uid, evse.uid)
        data = response.data.get('data')
        self.assertIsInstance(data, dict, msg='There should be a dict element "data" in the EVSE')
        connectors = data.get('connectors')
        self.assertIsInstance(connectors, list, msg='EVSE connectors should be a list')
        self.assertEqual(response.data.get('status_code'), 1000, msg='OCPI status code should be 1000 for success')

    def test_location_by_id(self):
        url = reverse('location-by-id',
                      args=[self.location.country_code, self.location.party_id, self.location.uid])

        request = api_factory.get(url)
        request.version = '2.2.1'
        loc = self.location
        viewset = LocationViewSet()
        viewset.request = request
        response = viewset.get(request, loc.country_code, loc.party_id, loc.uid)
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
        request.credentials = self.credentials
        return viewset().put(request, country_code=data.get('country_code'), party_id=data.get('party_id'), uid=data.get('id'))

    def post(self, url, data, token, viewset, use_credentials=True) -> OCPIResponse:
        request = api_factory.post(url, data, content_type="application/json",
                                  Authorization=f'Token {token}')
        request.data = data
        request.user = AnonymousUser
        request.credentials = self.credentials if use_credentials else None
        request.version = '2.2.1'
        return viewset().post(request)

    def test_put_location(self):
        url = reverse('location-list')
        token_base64 = self.credentials.ours_base64()

        invalid_data = dict(country_code=self.location.country_code, party_id=self.location.party_id, id=123)

        response = self.put(url, invalid_data, 'FALSETOKEN', LocationViewSet)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'A Location request should require OCPI authentication. '
                         f'{response.data}')
        self.assertEqual(response.data['status_code'], Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                         'The response OCPI status should be INVALID_OR_MISSING_PARAMETERS. '
                         f'{response.data}')

        response = self.put(url, invalid_data, token_base64, LocationViewSet)
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST,
            f'Badly formed but correctly authenticated request should produce http status code 400: {response.data}'
        )

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

        publish_allowed_to = [
            {
                "uid": "123123",
                "visual_number": "12345-67",
                "issuer": "NewMotion"
            }, {
                "uid": "321321",
                "visual_number": "0055375624",
                "issuer": "ANWB"
            }, {
                "uid": "12345678905880"
            }, {
                'visual_number': '0123456-99',
                'issuer': 'MoveMove'
            }
        ]

        for p in publish_allowed_to:
            Token.objects.create(type='RFID', contract_id='123', **p)

        for filename, country_code, party_id, http_status, ocpi_status, tariffs, evses, connectors in testcases:
            with self.subTest('Putting location', filename=filename):
                data = load_example(f'data/examples/{filename}.json')

                # Create the needed Tariffs
                for t in tariffs:
                    create_tariff(uid=t, country_code=country_code, party_id=party_id)

                create_credentialsrole(Party(country_code, party_id), role=OcpiRolesEnum.CPO,
                                       business_name='Test Business', website='http://example.com',
                                       credentials=self.credentials)

                # Send the request
                response = self.put(url, data, token_base64, LocationViewSet)
                self.assertEqual(response.status_code, http_status,
                                 f'Expected a HTTP status code {http_status} '
                                 f'for {filename} case: {response.data}.')
                self.assertEqual(response.data['status_code'], ocpi_status,
                                 f'Expected an OCPI status code {ocpi_status} '
                                 f'for {filename} case: {response.data}.')

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

            create_credentialsrole(Party(country_code, party_id), role=OcpiRolesEnum.CPO,
                                   business_name='Test Business', website='http://example.com',
                                   credentials=self.credentials)

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
        start_date_time = datetime(2022, 1, 1, 0, 0)
        evse = Evse.objects.all().first()
        location = evse.location
        connector = evse.connectors.first()
        credentials = Credentials.objects.first()
        session_params = dict(
            country_code='FI', party_id='FFF', start_date_time=start_date_time,
            cdr_token_uid='123', cdr_token_type='RFID', cdr_token_contract_id='123', auth_method='COMMAND',
            location=location, evse=evse, currency='EUR', status='ACTIVE',
            end_date_time=start_date_time + timedelta(hours=1), credentials=credentials, connector=connector,
            ocpi_master=credentials.roles.first()
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
            ('tariff_3_alt_url', dict(stop_kwh=Decimal(20.45)), 5.63, 6.24),

            # Parking, weekdays, times
            # ('tariff_4_complex', dict(stop_kwh=20.45), 5.63, 6.24),

        )
        for filename, case_params, excl_vat, incl_vat in testcases:
            with self.subTest(filename=filename):
                params = session_params.copy()
                params.update(case_params)
                session: Session = Session.objects.create(uid=uuid.uuid4().hex, billed_to='FI*MSP',
                                                          **params)
                data = load_example(f'data/examples/{filename}.json')
                serializer = TariffSerializer(data=data)
                self.assertTrue(serializer.is_valid(),
                                f"Tariff doesn't serialize for file {filename}: {serializer.errors}")
                tariff = serializer.save()
                session.connector.tariff_ids.set([tariff])
                self.assertTrue(session.calculate_price(), 'Cannot calculate price.')
                # ic(filename, session.total_cost_excl_vat, session.total_cost_incl_vat)
                self.assertEqual(session.total_cost_excl_vat, excl_vat,
                                 f"Total cost excluding VAT doesn't match in case {filename}")
                self.assertEqual(session.total_cost_incl_vat, incl_vat,
                                 f"Total cost including VAT doesn't match in case {filename}")

    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://fakehost/stop/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
               'callback-invoicing_url': 'http://localhost/invoice/{uid}/',
           }.get(x))
    def test_post_cdr(self, _redis_store_mock: Mock):
        url = reverse('cdr-list')
        token_base64 = self.credentials.ours_base64()
        viewset = CdrViewSet

        invalid_data = dict(country_code=self.country_code, party_id=self.party_id, id=123)

        # Todo: The authentication test needs to include all the middware, so that the request is authenticated
        # response = self.post(url, invalid_data, 'FALSETOKEN', viewset, use_credentials=False)
        # self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
        #                  f'A {viewset} request should require OCPI authentication. '
        #                  f'{response.data}')
        # self.assertEqual(response.data['status_code'], Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        #                  f'The {viewset} response OCPI status should be INVALID_OR_MISSING_PARAMETERS. '
        #                  f'{response.data}')

        testcases = (
            ('cdr_example', status.HTTP_201_CREATED, 1000, 1,
             'http://testserver.test/ocpi/2.2.1/cdrs/BE/BEC/12345'),
            ('cdr_example2', status.HTTP_201_CREATED, 1000, 1,
             'http://testserver.test/ocpi/2.2.1/cdrs/FI/000/8297d92ff7d047c68727750b3b8ca559'),
        )

        for filename, http_status, ocpi_status, price_component_count, cdr_url \
                in testcases:
            with self.subTest(filename=filename):
                data = load_example(f'data/examples/{filename}.json')

                country_code = data.get('country_code')
                party_id = data.get('party_id')

                create_credentialsrole(Party(country_code, party_id), business_name='Test Business',
                                               website='http://example.com', role=OcpiRolesEnum.CPO,
                                               credentials=self.credentials)

                # Send the request
                response = self.post(url, data, token_base64, viewset)
                if response.status_code >= 300:
                    print(f'status_text: "{response.status_text}" for {filename} case.')
                    # ic(response.data)
                self.assertEqual(response.headers.get('Location'), cdr_url,
                                 f'Expected a Location header with different content for {filename} case.')
                self.assertEqual(response.status_code, http_status,
                                 f'Expected a HTTP status code {http_status} for {filename} case.')
                self.assertEqual(response.data['status_code'], ocpi_status,
                                 f'Expected an OCPI status code {ocpi_status} for {filename} case.')

                # Verify the saved data
                uid = data.get('id')
                saved_cdr = Cdr.objects.get(uid=uid)
                saved_data = CdrSerializer(saved_cdr, context={'version': '2.2.1'}).data
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
                ignored_fields = ('credit', 'total_time_cost', 'charging_periods', 'tariff_alt_text', 'detail_url')
                for i in ignored_fields:
                    saved_data.pop(i, None)
                    data.pop(i, None)
                # saved_data['tariffs'][0].pop('detail_url')
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
            with self.subTest(filename=filename):
                data = load_example(f'data/examples/{filename}.json')

                country_code = data.get('country_code')
                party_id = data.get('party_id')

                _credentialsrole = create_credentialsrole(Party(country_code, party_id), business_name='Test Business',
                                       website='http://example.com', role=OcpiRolesEnum.EMSP,
                                       credentials=self.credentials)

                # Send the request
                response = self.put(url, data, token_base64, viewset)
                # if response.status_text or response.status_code not in (200, 201):
                #     print(f'status_text: "{response.status_text}" for {filename} case.')
                #     ic(response.data)
                self.assertEqual(response.status_code, http_status,
                                 f'Expected a HTTP status code {http_status} for {filename} case: {response.data}.')
                self.assertEqual(response.data['status_code'], ocpi_status,
                                 f'Expected an OCPI status code {ocpi_status} for {filename} case: {response.data}.')

                # Verify the saved data
                uid = data.get('uid').upper()
                try:
                    saved_data = TokenSerializer(Token.objects.get(uid=uid)).data
                    # ic(saved_data)
                except Token.DoesNotExist:
                    print(f"Unable to verify token {uid} from database.")
                    token_list = [str(t) for t in Token.objects.all()]
                    print(f'Available Tokens: {token_list}')
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
        request.version = '2.2.1'
        request.accepted_media_type = 'text/html'  # To get the detail_url in the response
        request.credentials = self.credentials
        credentialsrole = request.credentials.get_role(Party(self.location.country_code, self.location.party_id))
        loc = self.location
        assert credentialsrole.country_code == loc.country_code and credentialsrole.party_id == loc.party_id
        viewset = LocationViewSet()
        viewset.request = request
        response = viewset.get(request, loc.country_code, loc.party_id, loc.uid)
        # ic(response, response.data)
        data = response.data.get('data')

        self.assertEqual(response.data.get('status_code'), 1000, msg='OCPI status code should be 1000 for success')

        detail_url = data.get('detail_url')
        self.assertURLEqual(detail_url, 'http://testserver.test/ocpi/2.2.1/locations/FI/F1/1',
                            'Location detail URL differs from expected')

        # This should fail without authentication
        result = self.client.get(detail_url)
        self.assertTrue(result.status_code in [401, 403], 'A Location request should require OCPI authentication.')

    def _create_credentials(self, country_code, party_id):
        roles, _created = CredentialsRole.objects.get_or_create(
            role='CPO', country_code=country_code,
            party_id=party_id, defaults=dict(business_details=self.business_details)
        )
        self.credentials.roles.add(roles)


def dump_tariffs():
    for t in Tariff.objects.all():
        serializer = TariffSerializer(t)
        ic(t.pk, serializer.data)


class TariffTests(TestCase):
    fixtures = ['ocpi22/data/defaulttariffs.json', 'ocpi22/data/initial.json', 'ocpi22/data/credentials.json']

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)

    def check_tariff(self, tariff, tariff_elements, price_components):
        self.assertEqual(tariff.tariff_elements.count(), tariff_elements,
                         f"Tariff #{tariff.pk} `{tariff}` doesn't have {tariff_elements} TariffElements")
        for e in tariff.tariff_elements.all():
            self.assertEqual(e.price_components.count(), price_components,
                             f"TariffElement #{e.pk} `{e}` doesn't have {price_components} PriceComponents")

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
        self.assertEqual(tariff.tariff_elements.all()[0].price_components.all()[0].price, 0.22)

    @patch('ocpi22.tasks.send_ocpi_request.delay')
    @patch('ocpi22.models.tariff.find_endpoints_by_roles')
    def test_delete_tariff(self, mock_find_endpoints_by_roles, mock_send_ocpi_request):
        previous_count = Tariff.objects.count()
        country_code, party_id = 'FI', 'MSP'
        t1 = create_tariff(uid='T1', country_code=country_code, party_id=party_id)
        # Try the HTTP DELETE for this tariff
        url = reverse('tariff-by-id', args=[country_code, party_id, t1.uid], version='2.2.1')
        request = api_factory.delete(url)
        request.version = '2.2.1'
        request.user = AnonymousUser()
        viewset = TariffViewSet()
        viewset.request = request
        credentialsrole = get_credentialsrole(credentials=None, party=Party(country_code, party_id))
        credentials = credentialsrole.credentials
        mock_find_endpoints_by_roles.return_value = [('http://fakeserver', 'THEIR_TOKEN',
                                                      country_code, party_id, credentials)]

        response = viewset.delete(request, country_code=country_code, party_id=party_id, uid=t1.uid)
        self.assertEqual(response.status_code, 200, 'Tariff should be deleted')
        self.assertEqual(Tariff.objects.count(), previous_count,
                         'There should be the same amount of Tariffs as when we started this test')
        self.assertTrue(mock_send_ocpi_request.called, 'send_ocpi_request should be called')
        args, kwargs = mock_send_ocpi_request.call_args
        self.assertEqual(args, ({}, 'http://fakeserver/FI/MSP/T1', 'THEIR_TOKEN', 'FI', 'MSP', 'FI', 'CPO'),
                         'send_ocpi_request arguments differ from expected')
        self.assertEqual(kwargs, {'credentials_id': 2, 'method': 'delete', 'title': 'Tariff'},
                         'send_ocpi_request keyword arguments differ from expected')

    @staticmethod
    def _create_credentials(country_code: str, party_id: str, role: OcpiRolesEnum) -> Credentials:
        credentials = Credentials.objects.create(version=221)
        business_details = BusinessDetails.objects.create(
            name='Test MSP', website='https://test.com', logo='https://test.com/logo.png')
        roles, _created = CredentialsRole.objects.get_or_create(
            role=role.value, country_code=country_code,
            party_id=party_id, defaults=dict(business_details=business_details)
        )
        credentials.roles.add(roles)
        return credentials


class CdrTests(TestCase):
    fixtures = [
        'ocpi22/data/initial.json',
        'ocpi22/data/test-database-1.json',
        'ocpi22/data/defaulttariffs.json'
    ]

    def load_location(self, filename):
        data = load_example(f'data/examples/{filename}.json')
        country_code = data['country_code']
        party_id = data['party_id']
        serializer = LocationSerializer(data=data,
                                        context=dict(request=api_factory.get('/'), party=Party(country_code, party_id)))
        if not serializer.is_valid():
            self.fail(serializer.errors)
        return serializer.save()

    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://fakehost/stop/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
               'callback-invoicing_url': 'http://localhost/invoice/{uid}/',
           }.get(x))
    def test_session_to_cdr(self, redis_store_mock: Mock):
        for t in [11, 12, 13]:
            create_tariff(uid=str(t), country_code='BE', party_id='BEC')
        location = self.load_location('location_example')
        evse = location.evses.first()
        connector = evse.connectors.first()
        credentials = Credentials.objects.first()

        # ic(connector, connector.get_tariffs()[0].price())

        session = Session.objects.create(
            country_code='FI',
            party_id='EON',
            ocpi_master=credentials.roles.first(),
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
            credentials=credentials,
            billed_to='FI*MSP',
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

        self.assertTrue(all(t.archived for t in cdr1.tariffs.all()),
                        'Cdr needs to point to only archived Tariffs, so that they are not modified anymore.')

        self.assertEqual(cdr1.tariffs.count(), 1,
                         'Cdr is missing a Tariff')

        # Remove the CDR so that we can generate another one
        cdr1.delete()

        # Remove Tariff from Connector, so that the DefaultTariff would be in use
        connector.tariff_ids.set([])

        self.assertTrue(session.calculate_price(),
                        'There should be sufficient information to calculate the Session price')
        self.assertEqual(session.total_cost_excl_vat, 2.86,
                         "Price without VAT doesn't seem right.")
        self.assertEqual(session.total_cost_incl_vat, 3.55,
                         "Price with VAT doesn't seem right.")

        cdr: Cdr = Cdr.create_based_on_session(session)

        # Check that Tariffs are archived copies and that they exist

        self.assertTrue(all(t.archived for t in cdr.tariffs.all()),
                        'Cdr needs to point to only archived Tariffs, so that they are not modified anymore')

        self.assertEqual(cdr.tariffs.count(), 1,
                         'Cdr is missing a Tariff')

        self.assertEqual(cdr.tariffs.all()[0].uid, 'TTYPE2',
                         'This CDR should have a DefaultTariff, since no Tariff is specified for the Connector')

        self.assertEqual(cdr.billed_to, session.billed_to, 'Billed_to seems not to be copied correctly')


class mock_uuid4():
    number: int

    def __init__(self, number=1):
        self.number = number

    @property
    def hex(self):
        return f'MOCK-{self.number}'


class CommandTests(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']
    maxDiff = 10000

    @time_machine.travel(faketime, tick=False)
    # @patch('ocpi22.tokens.auth.ocpi_post', side_effect=[make_json_response(accept_authorization)])
    @patch('ocpi22.ocpi.util.uuid.uuid4',
           return_value=mock_uuid4())
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://john:his-password@fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://john:his-password@fakehost/stop/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
           }.get(x))
    @patch('ocpi22.webhooks.requests.post')
    def test_start_stop_session(self, requests_post_mock: Mock, _redis_get_mock: Mock, uuid4_mock: Mock):
        url = reverse('commands-start-session')
        viewset = CommandsViewSet()

        # Make sure an empty get doesn't cause validation errors, since we expect the user to just get some instructions
        request = api_factory.get(url, sender=Party('FI', 'MSP'))
        request.data = {}
        response = viewset.start_session(request)

        check_ok_result(self, response, http_status=status.HTTP_400_BAD_REQUEST)

        # Load up the test message and send it
        data = load_example(f'data/examples/command_start_session.json')

        billed_party = Party('FI', 'MSP')
        request = api_factory.post(url, sender=Party('FI', 'MSP'))
        request.data = data

        self.assertFalse(Session.objects.all().exists(),
                         'Please make sure there are no Sessions at the start of this test')

        # Let's pretend to be the CPO and get an error from charger
        requests_post_mock.return_value = make_json_response(dict(result='EVSE_INOPERATIVE'))
        requests_post_mock.reset_mock()
        uuid4_mock.return_value = mock_uuid4(42)

        try:
            response = viewset.start_session(request)
        except redis.exceptions.ConnectionError as e:
            print(f'This test requires a local Redis instance to be running: {e}')
            return False

        # Check the request sent to the CPO
        requests_post_mock.assert_called_once()
        args, kwargs = requests_post_mock.call_args
        self.assertFalse(args, 'Not expecting positional arguments to requests.post()')
        self.assertTrue(compare_dicts_recursively(response.data, SessionCommandsData.evse_inoperative_response),
                        'Expecting different response for start_session')

        # Let's pretend to be the CPO and all is good
        requests_post_mock.return_value = make_json_response(dict(result='ACCEPTED'))
        requests_post_mock.reset_mock()
        uuid4_mock.return_value = mock_uuid4(99)

        response = viewset.start_session(request)

        # Check the request sent to the CPO
        requests_post_mock.assert_called_once()
        args, kwargs = requests_post_mock.call_args
        self.assertFalse(args, 'Not expecting positional arguments to requests.post()')
        self.assertTrue(compare_dicts_recursively(kwargs, SessionCommandsData.start_webhook))

        # Let's guess the new Session
        session = Session.objects.all().first()

        check_ok_result(self, response)

        self.assertEqual(response.data.get('data').get('result'), 'ACCEPTED',
                         msg='Expecting the result "ACCEPTED"')

        session = Session.objects.get(status='PENDING')
        self.assertEqual(session.evse.uid, 'HELSINKI-3', "Session UID doesn't match expectation")

        # Let's pick a connector and fill out charging details
        session.connector = session.evse.connectors.all()[0]
        session.stop_kwh = 10.0
        session.total_cost_excl_vat = 4
        session.total_cost_incl_vat = 5
        session.save()

        #
        # Stop session, successful case
        #

        requests_post_mock.return_value = make_json_response(dict(result=CommandResponse.ACCEPTED))
        requests_post_mock.reset_mock()
        uuid4_mock.return_value = mock_uuid4(99)

        data = dict(session_id=session.uid, response_url='http://localhost.local/response/')

        with patch('ocpi22.commands.commands.generate_random_token') as mock_generate_random_token:
            mock_generate_random_token.return_value = 'COMMAND_ID'
            response = stop_session(data, AnonymousUser)

        calls = requests_post_mock.call_args_list
        requests_post_mock.assert_called_once()
        self.assertTrue(compare_dicts_recursively(calls[0].kwargs, SessionCommandsData.stop_webhook))
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         f'Stop session was expected to succeed: response.data')
        self.assertTrue(compare_dicts_recursively(response.data, SessionCommandsData.stop_success))

    @time_machine.travel(faketime, tick=False)
    # @patch('ocpi22.tokens.auth.ocpi_post', side_effect=[make_json_response(accept_authorization)])
    @patch('ocpi22.ocpi.util.uuid.uuid4',
           return_value=mock_uuid4())
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://john:his-password@fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://john:his-password@fakehost/stop/{evse_id}/',
               'callback-reserve_now_url': 'http://john:his-password@fakehost/reserve/{location_id}/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
           }.get(x, 'http://localhost/fallback/'))
    # @patch('ocpi22.webhooks.requests.post')
    def test_reserve_now(self, _redis_get_mock: Mock, uuid4_mock: Mock):
        url = reverse('commands-reserve-now')
        viewset = CommandsViewSet()

        # Make sure an empty get doesn't cause validation errors, since we expect the user to just get some instructions
        request = api_factory.get(url, sender=Party('FI', 'MSP'))
        request.data = {}

        with patch('ocpi22.webhooks.requests.post') as _mock_requests_post:
            response = viewset.reserve_now(request)

        check_ok_result(self, response, http_status=status.HTTP_400_BAD_REQUEST)

        # Load up the test message and send it
        data = load_example(f'data/examples/command_reserve_now.json')

        request = api_factory.post(url, sender=Party('FI', 'MSP'))
        request.data = data

        self.assertFalse(Session.objects.all().exists(),
                         'Please make sure there are no Sessions at the start of this test')

        try:
            with patch('ocpi22.webhooks.requests.post') as mock_requests_post:
                # Let's pretend to be the CPO and get an error from charger
                mock_requests_post.return_value = make_json_response(dict(result='EVSE_INOPERATIVE'))
                uuid4_mock.return_value = mock_uuid4(42)
                response = viewset.reserve_now(request)
        except redis.exceptions.ConnectionError as e:
            print(f'This test requires a local Redis instance to be running: {e}')
            self.fail()

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE,
                         'Expecting the reservation to fail')

        # Check the request sent to the CPO
        mock_requests_post.assert_called_once()
        args, kwargs = mock_requests_post.call_args
        self.assertFalse(args, 'Not expecting positional arguments to requests.post()')
        self.assertTrue(compare_dicts_recursively(response.data, SessionCommandsData.evse_inoperative_response),
                        'Expecting a different response for a reservation')

        cpo_credentialsrole = get_credentialsrole(None, Party('FI', 'CPO'))

        # Clear out any Sessions which prevent new charging sessions and reservations
        Session.objects.filter(status__in=[Session.PENDING, Session.ACTIVE]).update(status=Session.COMPLETED)
        Session.objects.all().update(ocpi_master=cpo_credentialsrole)

        with patch('ocpi22.webhooks.requests.post') as mock_requests_post:
            # Let's simulate the CPO backend
            mock_requests_post.return_value = make_json_response(dict(result='ACCEPTED'))
            uuid4_mock.return_value = mock_uuid4(99)
            response = viewset.reserve_now(request)

        # Check the request sent to the CPO
        mock_requests_post.assert_called_once()
        args, kwargs = mock_requests_post.call_args
        self.assertFalse(args, 'Not expecting positional arguments to requests.post()')
        self.assertTrue(compare_dicts_recursively(
            kwargs.get('json'),
            {
                'response_url': 'http://testserver.test/api/cpo/v2/chargepoint/remote_command_result/AUTH-REFERENCE/',
                'token_id': 'FI*001*T*ADMIN*TOKEN', 'token_type': 'OTHER', 'authorization_reference': 'AUTH-REFERENCE',
                'auth_method': 'COMMAND', 'from_party': 'FI*MSP',
                'location_id': 'HELSINKI-1', 'evse_id': 'HELSINKI-3', 'connector_id': None, 'billed_to': 'FI*MSP',
                'expiry_date': '2022-01-12T19:44:39.298178', 'reservation_id': 'RESERVATION-ID'
            }, 'Expecting a different response for a reservation')
        )

        check_ok_result(self, response)

        self.assertEqual(response.data.get('data').get('result'), 'ACCEPTED',
                         msg='Expecting the result "ACCEPTED"')

        session = Session.objects.get(status='PENDING')
        self.assertEqual(session.evse.uid, 'HELSINKI-3', "Session UID doesn't match expectation")

    # def test_unlock_connector(self):
    #     url = reverse('commands-unlock-connector')
    #     viewset = CommandsViewSet()
    #
    #     # Make sure an empty get doesn't cause validation errors, since we expect the user to just get some instructions
    #     request = api_factory.get(url)
    #     request.data = {}
    #     response = viewset.unlock_connector(request)
    #
    #     check_ok_result(self, response, http_status=status.HTTP_400_BAD_REQUEST)
    #
    #     # Load up the test message and send it
    #     data = load_example(f'data/examples/command_unlock_connector.json')
    #
    #     request = api_factory.post(url)
    #     request.data = data
    #     response = viewset.unlock_connector(request)
    #
    #     check_ok_result(self, response, command_result=CommandResponse.ACCEPTED)
    #
    #     data = load_example(f'data/examples/command_unlock_connector_unknown_location.json')
    #
    #     request = api_factory.post(url)
    #     request.data = data
    #     response = viewset.unlock_connector(request)
    #
    #     check_ok_result(self, response, http_status=status.HTTP_400_BAD_REQUEST,
    #                     status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS)


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
        with time_machine.travel(faketime, tick=False):
            token = get_admin_token()
        serializer = TokenSerializer(token)
        expected = {  # 'detail_url': 'http://testserver.test/ocpi/2.2.1/tokens/FI/MSP/FI*MSP*T*ADMIN*TOKEN',
            'contract_id': 'INTERNAL',
            'country_code': 'FI',
            'issuer': 'FI*MSP',
            'party_id': 'MSP',
            'type': 'OTHER',
            'uid': 'FI*MSP*T*ADMIN*TOKEN',
            'valid': True,
            'last_updated': '2022-01-01T12:00:00Z'
        }
        self.assertTrue(compare_dicts_recursively(serializer.data, expected),
                        'Getting the admin token seems not to work')

        # Creating the admin token
        token.delete()
        with time_machine.travel(faketime, tick=False):
            token = get_admin_token()
        serializer = TokenSerializer(token)
        self.assertTrue(compare_dicts_recursively(serializer.data, expected),
                        'Creating the admin token seems not to work')

    @time_machine.travel(datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc), tick=False)
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

        # args, kwargs = mock_put.call_args

        args_list = mock_put.call_args_list
        self.assertEqual(len(args_list), 3, 'Expecting three calls to requests.put()')

        args, kwargs = args_list[1].args, args_list[1].kwargs

        expected_headers = {'Authorization': 'Token '
                                             'QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==',
                            'OCPI-from-country-code': 'FI',
                            'OCPI-from-party-id': 'MSP',  # Tokens are owned by MSP, we should send with MSP identity
                            'OCPI-to-country-code': 'FI',
                            'OCPI-to-party-id': 'HUB',  # The recipient comes from the Credentials in the fixture
                            'content-type': 'application/json'}
        expected_data = {'contract_id': 'CONTRACT',
                         'country_code': 'FI',
                         'issuer': 'issuer',
                         'last_updated': '2022-01-01T12:00:00Z',
                         'party_id': 'MSP',
                         'type': 'RFID',
                         'uid': 'UID',
                         'valid': True,
                         'whitelist': 'ALWAYS'}

        self.assertEqual(kwargs['url'], 'http://localhost:8001/ocpi/2.2.1/tokens/',
                         'Expected to send the update to another address')
        assert (isinstance(expected_headers, dict))
        assert (isinstance(kwargs['headers'], dict))
        self.assertTrue(compare_dicts_recursively(kwargs['headers'], expected_headers),
                        'Headers differ from expected')
        self.assertTrue(compare_dicts_recursively(kwargs['data'], expected_data),
                        'JSON content differs from expected')


def check_ok_result(testcase: TestCase, response, status_code: int = 1000, http_status: int = 200,
                    command_result: str = None) -> None:
    testcase.assertEqual(response.data.get('status_code'), status_code,
                         msg=f'Expecting OCPI status code {status_code}: {response}, {response.data}')
    testcase.assertEqual(response.status_code, http_status,
                         msg=f'Expecting HTTP status code {http_status}: {response}, {response.data}')
    if command_result:
        testcase.assertEqual(response.data.get('data').get('result'), command_result,
                             msg=f'Expecting the result "{command_result}": {response}, {response.data}')


fake_token = '1234567890'


class TestCredentials(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']

    def mocked_credentials_get(url, *_args, **_kwargs):
        assert isinstance(url, str)
        # ic(url, _args, _kwargs)

        response_data = {
            'http://localhost/versions': {'data': [{'url': 'http://localhost/ocpi/2.2.1/', 'version': '2.2'}]},
            'http://localhost/ocpi/2.2.1/': ocpi_endpoints_response,
            'http://localhost/ocpi/2.2.1/credentials': ocpi_endpoints_response,
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

        expected_headers = {'Accept': 'application/json', 'Authorization': 'Token OTE4Mjcz'}

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
                         'url': 'http://testserver.test/ocpi/versions/'}

        json_data = kwargs['json']
        # ic(json_data)
        # ic(kwargs['headers'])
        self.assertDictEqual(json_data, expected_data, 'Credentials endpoint gives an unexpected response')

    #
    # Due to the database foregnkeys, we can't delete a Credentials object
    # without deleting a large number of other permanent data
    #
    # Todo: Implement a permanent soft delete
    #
    # @time_machine.travel(faketime, tick=False)
    # @patch('ocpiconnector.management.commands.exchange_credentials.requests.delete',
    #        side_effect=mocked_credentials_delete)
    # def test_delete(self, mock_delete: Mock):
    #     credentials = Credentials.objects.get(pk=2)
    #     self.assertTrue(credentials.roles.count())
    #     self.assertTrue(credentials.endpoints.count())
    #     # ic(credentials)
    #
    #     credentials.delete()
    #
    #     mock_delete.assert_called_once()
    #
    #     # Let's examine what was actually sent
    #     args, kwargs = mock_delete.call_args
    #
    #     # ic(args, kwargs)
    #     expected_headers = {'Authorization': 'Token '
    #                                          'QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==',
    #                         'OCPI-from-country-code': 'FI',
    #                         'OCPI-from-party-id': 'CPO',
    #                         'OCPI-to-country-code': 'FI',
    #                         'OCPI-to-party-id': 'CP1',
    #                         'content-type': 'application/json'}
    #     self.assertDictEqual(kwargs.get('headers'), expected_headers,
    #                          f'Headers differ from expected')


class TestObjectPull(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']

    def setUp(self):
        our_party = get_our_party(role=OcpiRolesEnum.CPO)
        self.credentialsrole = create_credentialsrole(our_party, 'This is us', website='', role=OcpiRolesEnum.CPO)
        self.credentialsrole.agreed_parties.set(CredentialsRole.objects.all())
        invalidate_partner_cache(our_party)

    def mocked_object_get(url, *_args, **kwargs):
        try:
            credentials = Credentials.objects.get(pk=2)
            headers = kwargs['headers']
            # Let's swap the other token and receive this request as if it comes from outside
            headers['HTTP_AUTHORIZATION'] = f'Token {credentials.ours_base64()}'

            with patch('ocpi22.ocpi.auth.OCPIPermission.has_permission') as mock_has_permission:
                # We will test authentication separately, so let's just make this test simpler and more focused
                mock_has_permission.return_value = True
                result = client.get(url, **headers)

            json_text = result.content.decode('utf-8')
            assert 'DOCTYPE' not in json_text, f"URL {url} is returning HTML, when excepting JSON"

            content = json.loads(json_text)
            assert compare_dicts_recursively(content, expected_get_responses[url]), \
                f"Expecting a different result for {url}: {content}"

            response_headers = dict(result.headers)
            response_headers.pop('Content-Length', None)
            expected_headers = expected_get_headers[url]
            expected_headers.pop('Content-Length', None)
            assert compare_dicts_recursively(expected_headers, response_headers), \
                f"Expecting different headers for {url}: {response_headers}"

            return result
        except (AssertionError, KeyError):
            # ic(url, recursive_sort_dict(response_headers), recursive_sort_dict(expected_headers))
            # ic(recursive_sort_dict(content), recursive_sort_dict(expected_get_responses[url]))
            raise

    @time_machine.travel(faketime, tick=False)
    @patch('ocpiconnector.management.commands.exchange_credentials.requests.get', side_effect=mocked_object_get)
    def test_pull(self, _mock_get: Mock):
        settings.SEND_UPDATES = True
        settings.BACKGROUND_SEND = False

        credentials = Credentials.objects.get(pk=2)
        with patch('ocpi22.locations.location.get_partners') as mock_get_partners:
            mock_get_partners.return_value = set(range(0, 1000))  # Connected to everyone for the duration of this test
            schedule_full_update(credentials, countdown=0, limit=3)

        # Content is verified in mocked_object_get


class CredentialsTest(TestCase):
    fixtures = ['ocpi22/data/test-database-1.json']
    maxDiff = 99999

    def test_cached_partylist(self):
        location_url = urljoin("http://localhost:8001", reverse('location-list'))
        token_url = urljoin("http://localhost:8001", reverse('token-list'))
        tariff_url = urljoin("http://localhost:8001", reverse('tariff-list'))
        token = 'QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw=='

        testcases = (
            (Location, [(location_url, token, 'FI', 'MSP'),
                        (location_url, token, 'FI', 'NAP'),
                        (location_url, token, 'FI', 'HUB')]),
            (Token, [(token_url, token, 'FI', 'CP1'),
                     (token_url, token, 'FI', 'HUB'),
                     (token_url, token, 'FI', '000'),
                     ]),
            (Tariff, [(tariff_url, token, 'FI', 'MSP'),
                      (tariff_url, token, 'FI', 'NAP'),
                      (tariff_url, token, 'FI', 'HUB')]),
        )
        counter = 0
        ocpi_object: OcpiModule
        for ocpi_object, endpoints_result in testcases:
            with self.subTest(endpoints_result=endpoints_result):
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

                endpoints = [e[:4] for e in endpoints]  # Skip the Credentials, I don't know how to match it
                self.assertEqual(
                    endpoints, endpoints_result,
                    f'Cannot find the right endpoints for {roles} to send updates to'
                )

        # Check that changes to Credentials reset the endpoint cache
        self.assertGreater(find_endpoints_by_roles.cache_info().currsize, 0)
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

            self.assertTrue(compare_dicts_recursively(asdict(route), {'alive': True,
                                                                      'credentials_id': 2,
                                                                      'direct': True,
                                                                      'identifier': OcpiModuleEnum.LOCATIONS,
                                                                      'to': {'country_code': 'FI', 'party_id': 'MSP'},
                                                                      'token_base64': 'dGhlaXJzLTI=',
                                                                      'url': 'http://localhost:8001/ocpi/nap/2.2/locations',
                                                                      'version': '2.2'}),
                            'Expected route not found'
                            )
        except AttributeError as e:
            self.fail(f"find_route() is probably not cached: {e}")

    def test_find_hub_route(self):
        # Route to an unknown party
        route: Route = find_route(Party('no', 'exi'), OcpiModuleEnum.LOCATIONS)
        self.assertTrue(route.through_hub, 'Seems that a hub route is not found')
        self.assertTrue(compare_dicts_recursively(asdict(route), {'alive': True,
                                                                  'credentials_id': 3,
                                                                  'direct': False,
                                                                  'identifier': OcpiModuleEnum.LOCATIONS,
                                                                  'to': {'country_code': 'FI', 'party_id': 'HUB'},
                                                                  'token_base64': 'dGhlaXJzLTM=',
                                                                  'url': 'http://localhost:8001/ocpi/hub/2.2/locations',
                                                                  'version': '22'}),
                        'Expecting a different route through hub'
                        )

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

        data = {
            'message': 'This is a message routing test',
            'response_url': 'http://localhost/ocpi/hub/2.2/commands/1234'
        }
        credentials = Credentials.objects.get(pk=2)
        sender = Party('FI', 'MSP')

        def fake_get_response(_request):
            # We want to know when this gets called
            self.get_response_called = True
            return HttpResponse('Everything is good', status=status.HTTP_200_OK)

        test_cases = (
            dict(label='All good', result=200),
            dict(label='Missing token', token='', result=401),
            dict(label='Unknown recipient', party=Party('NO', 'NOT'), result=404),
            dict(label='Missing recipient', party=Party('', ''), result=200),  # This should be ok, or no Admin UI
            dict(label='Hub as recipient', party=Party('FI', 'HUB'), result=200, routing=False, this_is_us=True),
        )

        for testcase in test_cases:
            with self.subTest(testcase.get('label')):

                # Todo: with self.subTest(testcase)
                mock_request.reset_mock()
                routing = testcase.get('routing', True)
                mock_is_our_identifier.return_value = testcase.get('this_is_us')
                to = testcase.get('party')
                if to is None:  # Let empty Party through
                    to = Party('FI', 'CPO')
                headers = make_headers(testcase.get('token', credentials.ours_base64()), to, sender)
                request = api_factory.post(url, **headers)

                # Combine META with headers, since both might be used in tests
                request.headers = request.META | headers
                request.META = request.headers

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


class TestSession(TestCase):
    fixtures = ['ocpi22/data/test-database-sessions.json']
    maxDiff = None

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://localhost/start/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/'
           }.get(x, 'http://localhost/fallback/'))
    @patch('ocpi22.ocpi.util.uuid.uuid4',
           return_value=mock_uuid4())
    @patch('ocpi22.tokens.auth.ocpi_post', side_effect=[make_json_response(accept_authorization)])
    def test_update_session(self,
                            _ocpi_post_mock: Mock,
                            _uuid4_mock: Mock,
                            _get_parameter_mock: Mock):
        evse = Evse.objects.all()[0]
        location = evse.location
        uid = '12345'
        credentials = Credentials.objects.first()
        authorization_reference = 'MOCK-AUTHORIZATION-REFERENCE'
        party = credentials.get_party_for_role(OcpiRolesEnum.EMSP)
        session = create_session(location.uid, evse.uid, 1, token_id="T1", credentials=credentials, uid=uid,
                                 billed_to=party,
                                 authorization_reference=authorization_reference,
                                 ocpi_master=create_credentialsrole(Party('FI', 'CPO'),
                                                                    business_name='This is us', website='',
                                                                    role=OcpiRolesEnum.CPO))
        self.assertTrue(bool(session))
        # ic(session)

        test_cases = (
            ('session_patch_example_charging_period', 200, 0.8, 1,
             None, None),
            ('session_patch_example_charging_period_update_1', 200, 1.0, 1,
             ExpectedSessionUpdateResults.update1, ExpectedSessionUpdateResults.webhook1),
            ('session_patch_example_charging_period_update_2', 200, 1.1, 2,
             ExpectedSessionUpdateResults.update2, ExpectedSessionUpdateResults.webhook2),
        )

        kwargs = dict(country_code=session.country_code, party_id=session.party_id, uid=session.uid)
        session_url = reverse('session-by-id', kwargs=kwargs)
        request = api_factory.patch(session_url)
        request.credentials = Credentials.objects.get(pk=2)
        Authorization.objects.create(authorization_reference=authorization_reference)
        credentialsrole = create_credentialsrole(party, 'This is us', website='', role=OcpiRolesEnum.CPO)
        request.ocpi_party = credentialsrole
        party = Party('FI', 'CPO')
        # args = (party.country_code, party.party_id, session.uid)
        request.path = reverse('session-by-id', kwargs=kwargs)
        request.accepted_media_type = 'text/html'  # To get the detail_url in the response

        for filename, status_code, cost, charging_period_count, expected_dict, expected_webhook_data in test_cases:
            with self.subTest(filename=filename):
                data = load_example(f'data/examples/{filename}.json')
                request.data = data

                with patch('ocpi22.util.redis_store.get') as mock_get, \
                        patch('ocpi22.webhooks.requests.post') as webhook_post_mock:
                    mock_get.return_value = 'http://localhost/session/'
                    response = SessionViewSet().patch(request, **kwargs)

                calls = webhook_post_mock.call_args_list
                webhook_post_mock.assert_called_once()
                if expected_webhook_data:
                    self.assertTrue(compare_dicts_recursively(calls[0].kwargs['json'], expected_webhook_data),
                                    f'Webhook data differs from expected')
                # ic()
                # kwargs = dict(calls[0])
                # ic(webhook_post_mock.call_args_list)  # webhook_post_mock.call_args makes the test explode

                # if expected_webhook_data:
                #     self.assertDictEqual(
                #         kwargs, expected_webhook_data, f'Data sent to webhook differs from expected'
                #     )

                self.assertEqual(response.status_code, status_code,
                                 f'Expecting status code {status_code}')

                session = Session.objects.get(uid=uid)
                self.assertEqual(session.total_cost_excl_vat, cost,
                                 f'Session price was not changed to {cost}')

                self.assertEqual(session.chargingperiods.count(), charging_period_count,
                                 f'Expecting {charging_period_count} ChargingPeriods')

                if expected_dict:
                    session_data = SessionSerializer(instance=session).data
                    # ic(recursive_sort_dict(session_data), recursive_sort_dict(expected_dict))
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
                response={'status_text': 'EVSE with ID NON-EXISTENT-EVSE does not exist in the system '
                                         'database for party FI*CPO'},
                status_code=404
            ),
        )

        for case in testcases:
            with self.subTest(request=case.get('request')):
                cpo_request.data = case.get('request')
                cpo_response = cpo_viewset.status_change(cpo_request)

                self.assertEqual(cpo_response.status_code, case.get('status_code'),
                                 'Status change should succeed')
                self.assertDictEqual(cpo_response.data, case.get('response'),
                                     f'Case request {case.get("request")}, response {case.get("response")}')
                if cpo_response.status_code != 404:
                    evse = Evse.objects.get(uid=case.get('request').get('evse_id'))
                    self.assertEqual(evse.status, case.get('evse_status'))

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://localhost/start/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
               'callback-invoicing_url': 'http://localhost/invoice/{uid}/',
           }.get(x))
    @patch('ocpi22.ocpi.util.uuid.uuid4',
           return_value=mock_uuid4())
    @patch('ocpi22.tokens.auth.ocpi_post', side_effect=[make_json_response(accept_authorization)])
    @patch('ocpi22.webhooks.requests.post')
    @patch('ocpiconnector.analytics.send_session_update_to_analytics')
    def test_rfid_charging_flow(self,
                                _send_analytics: Mock,
                                _webhook_post_mock: Mock,
                                _ocpi_post_mock: Mock,
                                _uuid4_mock: Mock,
                                _get_parameter_mock: Mock):

        evse = Evse.objects.get(uid='HELSINKI-3')
        self.assertEqual(evse.status, 'AVAILABLE')

        start_transaction_url = reverse('chargepoint-start-transaction')
        cpo_viewset = ChargePointViewSet()
        cpo_request = api_factory.post(start_transaction_url)
        cpo_request.credentials = Credentials.objects.first()
        cpo_request.accepted_media_type = 'text/html'  # To get the detail_url in the response
        cpo_request.version = '2.2.1'
        cpo_request.data = {
            "evse_id": "HELSINKI-3",
            "connector_id": "1",
            "token_id": "EKI1",
            "internal_reference": "MY-INTERNAL-REFERENCE",
            "start_kwh": 120
        }
        with patch('ocpi22.ocpi.util.OcpiModule.send_background_update') as send_updates_mock:
            cpo_response = cpo_viewset.start_transaction(cpo_request)

            # Make sure the created Session was sent to the relevant party
            send_updates_mock.assert_called()
            args, kwargs = send_updates_mock.call_args

            data_sent = args[0]

        # ic(recursive_sort_dict(data_sent), recursive_sort_dict(RfidTestData.expected_data_1))
        self.assertTrue(compare_dicts_recursively(data_sent, RfidTestData.expected_data_1),
                        "The Session update doesn't look as expected")

        self.assertEqual(cpo_response.status_code, 200, 'Start session should succeed')
        # ic(recursive_sort_dict(cpo_response.data))
        self.assertEqual(cpo_response.data,
                         {'session': {'detail_url': 'http://testserver.test/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1',
                                      'auth_method': 'AUTH_REQUEST',
                                      'authorization_reference': 'MOCK-AUTHORIZATION-REFERENCE',
                                      'billed_to': 'FI*MSP',
                                      'connector_id': '1',
                                      'currency': 'EUR',
                                      'evse_uid': 'HELSINKI-3',
                                      'internal_reference': 'MY-INTERNAL-REFERENCE',
                                      'location_id': 'HELSINKI-1',
                                      'session_id': 'FI*CPO*S*MOCK-1',
                                      'start_date_time': '2022-01-01T12:00:00Z',
                                      'start_kwh': 120.0,
                                      'stop_kwh': 120.0,
                                      'status': 'ACTIVE',
                                      'last_updated': '2022-01-01T12:00:00Z',
                                      'token': OrderedDict([('token_id', 'EKI1'),
                                                            ('type', 'RFID'),
                                                            ('contract_id', 'DE8ACC12E46L89')])},
                          'status_text': 'Session started'}
                         )

        # Duplicate internal_reference
        response = cpo_viewset.start_transaction(cpo_request)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT,
                         'Duplicate internal_reference shoud cause an error')

        testcases = (
            dict(
                request=dict(
                    internal_reference='MY-INTERNAL-REFERENCE',
                    kwh=123.45,
                    soc=42,
                ),
                expected_response={'now_kwh': 123.45,
                                   'power': None,
                                   'price': '2,14€',
                                   'session_id': 'FI*CPO*S*MOCK-1',
                                   'internal_reference': 'MY-INTERNAL-REFERENCE',
                                   'soc': 42.0,
                                   'start_kwh': 120.0,
                                   'status_text': 'Session updated',
                                   'total_kwh': Decimal('3.450')},
                session_data={  # 'detail_url': 'http://testserver.test/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1',
                    'auth_method': 'AUTH_REQUEST',
                    'authorization_reference': 'MOCK-AUTHORIZATION-REFERENCE',
                    'cdr_token': OrderedDict([('uid', 'EKI1'),
                                              ('type', 'RFID'),
                                              ('contract_id', 'DE8ACC12E46L89')]),
                    'charging_periods': [OrderedDict([('start_date_time', '2022-01-01T12:00:00Z'),
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
                    'start_date_time': '2022-01-01T12:00:00Z',
                    'status': 'ACTIVE',
                    'last_updated': '2022-01-01T12:00:00Z',
                    'total_cost': OrderedDict([('excl_vat', 1.73), ('incl_vat', 2.14)]),
                    'id': 'FI*CPO*S*MOCK-1'},
                expected_update_data={'charging_periods': [OrderedDict(
                    [('start_date_time', '2022-01-01T12:00:00Z'), ('tariff', 'EKI1'), ('dimensions', [
                        OrderedDict([('type', 'ENERGY'), ('volume', '3.4500')]),
                        OrderedDict([('type', 'STATE_OF_CHARGE'), ('volume', '42.0000')])])])],
                    'kwh': Decimal('3.450'),
                    'last_updated': '2022-01-01T12:00:00Z',
                    'total_cost': {'excl_vat': 1.73, 'incl_vat': 2.14}},
                evse_status='CHARGING'
            ),
            dict(
                request=dict(
                    internal_reference='MY-INTERNAL-REFERENCE',
                    kwh=153.45,
                    soc=80,
                ),
                expected_response={'now_kwh': 153.45,
                                   'power': None,
                                   'price': '20,74€',
                                   'session_id': 'FI*CPO*S*MOCK-1',
                                   'internal_reference': 'MY-INTERNAL-REFERENCE',
                                   'soc': 80.0,
                                   'start_kwh': 120.0,
                                   'status_text': 'Session updated',
                                   'total_kwh': Decimal('33.450')},
                session_data={  # 'detail_url': 'http://testserver.test/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1',
                    'auth_method': 'AUTH_REQUEST',
                    'authorization_reference': 'MOCK-AUTHORIZATION-REFERENCE',
                    'cdr_token': OrderedDict([('uid', 'EKI1'),
                                              ('type', 'RFID'),
                                              ('contract_id', 'DE8ACC12E46L89')]),
                    'charging_periods': [OrderedDict([('start_date_time', '2022-01-01T12:00:00Z'),
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
                    'start_date_time': '2022-01-01T12:00:00Z',
                    'status': 'ACTIVE',
                    'last_updated': '2022-01-01T12:00:00Z',
                    'total_cost': OrderedDict([('excl_vat', 16.73), ('incl_vat', 20.74)]),
                    'id': 'FI*CPO*S*MOCK-1'},
                evse_status='CHARGING'
            ),
            dict(
                request=dict(
                    internal_reference='MY-INTERNAL-REFERENCE',
                    kwh=0,
                ),
                expected_response={'internal_reference': 'MY-INTERNAL-REFERENCE',
               'now_kwh': 0.0,
               'power': None,
               'price': '-',
               'session_id': 'FI*CPO*S*MOCK-1',
               'soc': None,
               'start_kwh': 120.0,
               'status_text': 'Session updated',
               'total_kwh': Decimal('0.000')},
                status_code=200,
            ),
            dict(
                request=dict(
                    session_id='NON-EXISTENT-SESSION',
                    kwh=123.45,
                ),
                expected_response={'status': 'Session matching query does not exist.'},
                status_code=404,
            ),
        )

        for case in testcases:
            with self.subTest(request=case.get('request')), \
                    patch('ocpi22.ocpi.util.OcpiModule.send_background_update') as send_updates_mock:
                data = case.get('request')
                # request.accepted_media_type = 'text/html'  # To get the detail_url in the response
                # request.version = '2.2.1'
                cpo_response = meter_values(data)

                expected_status = case.get('status_code', 200)
                self.assertEqual(cpo_response.status_code, expected_status,
                                 f'Expecting HTTP status {expected_status} for {case.get("request")}')
                self.assertTrue(
                    compare_dicts_recursively(cpo_response.data, case.get('expected_response'), label=data.get('kwh')),
                    f'Case request {case.get("request")}, response {cpo_response.data}')

                # Make sure the updated session was sent after meter_values was called
                if expected_status == 200:
                    send_updates_mock.assert_called()
                    args, kwargs = send_updates_mock.call_args
                    # Check the outgoing update call
                    expected_update_data = case.get('expected_update_data')
                    if expected_update_data:
                        update_data = args[0]
                        expected_serializer = SessionSerializer(data=update_data, partial=True)
                        self.assertTrue(expected_serializer.is_valid(),
                                        f'The Session update data does not comply with schema: {expected_serializer.errors}')
                        self.assertTrue(update_data.get('charging_periods'),
                                        'Charging periods missing from Session update')
                        self.assertTrue(
                            compare_dicts_recursively(update_data, expected_update_data, label=data.get('kwh')),
                            f'Sending Session update differs from expected')

                    expected_session_data = case.get('session_data')
                    if expected_session_data:
                        session = Session.objects.get(internal_reference=cpo_request.data.get('internal_reference'))
                        self.assertTrue(session.total_cost_excl_vat and session.total_cost_incl_vat,
                                        'meter_values does not result in an updated price for the session')
                        session_data = SessionSerializer(instance=session).data
                        # ic(recursive_sort_dict(session_data), recursive_sort_dict(expected_session_data))
                        self.assertDictEqual(session_data, expected_session_data,
                                             'Session data differs')

        #
        # CPO stops the session
        #

        data = dict(
            internal_reference='MY-INTERNAL-REFERENCE',
            stop_kwh=155,
            stop_timestamp=faketime + timedelta(minutes=60)  # This should apply, in case of a connection problem
        )
        with time_machine.travel(faketime + timedelta(minutes=90), tick=False), \
                patch('ocpi22.ocpi.util.OcpiModule.send_background_update') as send_updates_mock:
            response = stop_transaction(data)

        # ic(recursive_sort_dict(response.data), recursive_sort_dict(StopTransactionResponses.stop1))
        self.assertEqual(recursive_sort_dict(response.data), recursive_sort_dict(StopTransactionResponses.stop1),
                         'stop_transaction response differs from expected')
        send_updates_mock.assert_called()
        args, kwargs = send_updates_mock.call_args
        sent_data = args[0]
        # ic(recursive_sort_dict(sent_data), recursive_sort_dict(SessionData.stop4))
        self.assertDictEqual(recursive_sort_dict(sent_data), recursive_sort_dict(SessionData.stop4),
                             'stop_transaction is sending different session data than expected to MSP')

    @time_machine.travel(faketime, tick=False)
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://fakehost/stop/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
               'callback-invoicing_url': 'http://localhost/invoice/{uid}/',
           }.get(x))
    @patch('ocpi22.util.redis_store.set', return_value=True)
    @patch('ocpi22.ocpi.util.uuid.uuid4',
           return_value=mock_uuid4())
    @patch('ocpi22.webhooks.requests.post')
    @patch('ocpi22.webhooks.requests.post')
    def test_adhoc_token(self,
                         _webhook_post_mock: Mock,
                         requests_post_mock: Mock,
                         uuid4_mock: Mock,
                         _set_parameter_mock: Mock,
                         _get_parameter_mock: Mock):
        url = reverse('commands-start-session')
        viewset = CommandsViewSet()

        # Load up the test message and send it
        data = load_example(f'data/examples/command_start_session_adhoc.json')

        billed_party = Party('FI', 'MSP')
        request = api_factory.post(url, sender=billed_party)
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
        authorization_reference = 'FI*001-AUTH-REFERENCE'
        url = f'http://testserver.test/api/cpo/v2/chargepoint/remote_command_result/{authorization_reference}/'
        self.assertDictEqual(
            kwargs.get('json'),
            {'auth_method': 'COMMAND',
             'authorization_reference': authorization_reference,
             'from_party': 'FI*MSP',
             'billed_to': 'FI*MSP',
             'connector_id': None,
             'evse_id': 'HELSINKI-3',
             'response_url': url,
             'token_id': 'SOME-ADHOC-TOKEN',
             'token_type': 'AD_HOC_USER'}
        )

        # Capture the data going to Redis
        # args, kwargs = set_parameter_mock.call_args
        # _key, value, _ttl = args
        # ic(_key, value)
        #
        # Command result
        #

        # Inject the data supposedly coming from Redis
        # get_parameter_mock.return_value = value

        data = dict(result='ACCEPTED')
        response = send_command_result(data, url, 'start', authorization_reference)

        self.assertDictEqual(
            response.data,
            {'data': {'command_id': 'FI*001-AUTH-REFERENCE'},
             'status_code': 1000,
             'status_message': 'Command result received, thank you!',
             'timestamp': '2022-01-01T12:00:00Z'}
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
        cpo_response = authorize(data)

        self.assertEqual(cpo_response.status_code, 200,
                         'Token should be authorized')
        self.assertTrue(compare_dicts_recursively(cpo_response.data, SessionCommandsData.authorization_success),
                        'Expecting authorization to succeed')

        #
        # Start session based on authorization from eMSP Command
        #

        data = dict(
            evse_id='HELSINKI-3',
            token_id='SOME-ADHOC-TOKEN',
            internal_reference='MY-INTERNAL-REFERENCE-2',
            connector_id='1',
        )
        cpo_response = start_transaction(data)

        # ic(recursive_sort_dict(cpo_response.data))
        self.assertDictEqual(
            cpo_response.data,
            {'session': {'detail_url': 'http://testserver.test/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1',
                         'auth_method': 'COMMAND',
                         'authorization_reference': 'FI*001-AUTH-REFERENCE',
                         'billed_to': 'FI*MSP',
                         'currency': 'EUR',
                         'evse_uid': 'HELSINKI-3',
                         'location_id': 'HELSINKI-1',
                         'connector_id': '1',
                         'session_id': 'FI*CPO*S*MOCK-1',
                         'internal_reference': 'MY-INTERNAL-REFERENCE-2',
                         'start_date_time': '2022-01-01T12:00:00Z',
                         'start_kwh': 0.0,
                         'stop_kwh': 0.0,
                         'status': 'ACTIVE',
                         'last_updated': '2022-01-01T12:00:00Z',
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

            # Clear authorization caches to get a clean start
            _get_authorization_from_sessions.cache_clear()
            _authorize_token.cache_clear()
            authorize_token.cache_clear()

            # Use a new Session UID
            uuid4_mock.return_value = mock_uuid4(3)

            cpo_response = authorize(data)
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

        uuid4_mock.return_value = mock_uuid4(2)
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

        data = dict(
            internal_reference='MY-INTERNAL-REFERENCE-2',
            kwh=123.45,
            soc=42,
            power=150
        )

        #
        # Try updating meter values for a non-active Session
        #

        Session.objects.filter(internal_reference='MY-INTERNAL-REFERENCE-2').update(status=Session.COMPLETED)

        cpo_response = meter_values(data)
        self.assertEqual(cpo_response.status_code, status.HTTP_403_FORBIDDEN)

        #
        # Try updating meter values without a tariff specified
        #

        session = Session.objects.get(internal_reference='MY-INTERNAL-REFERENCE-2')
        session.status = Session.ACTIVE
        session.save()
        connector = session.connector
        tariffs = connector.tariff_ids.all()
        connector.tariff_ids.clear()

        cpo_response = meter_values(data)

        self.assertEqual(cpo_response.status_code, status.HTTP_409_CONFLICT)
        connector.tariff_ids.set(tariffs)

        #
        # Update meter values with a tariff
        #

        session = Session.objects.get(internal_reference='MY-INTERNAL-REFERENCE-2')
        session.connector.tariff_ids.set([9])
        session.save()

        response = meter_values(data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.data,
                             {'now_kwh': 123.45,
                              'power': 150.0,
                              'price': '76,54€',
                              'session_id': 'FI*CPO*S*MOCK-1',
                              'internal_reference': 'MY-INTERNAL-REFERENCE-2',
                              'soc': 42.0,
                              'start_kwh': 0.0,
                              'status_text': 'Session updated',
                              'total_kwh': Decimal('123.450')})

        session = Session.objects.get(internal_reference='MY-INTERNAL-REFERENCE-2')
        session_data = SessionSerializer(session).data
        # ic(recursive_sort_dict(session_data), recursive_sort_dict(SessionData.meter_values_1))
        self.assertEqual(session_data, SessionData.meter_values_1, 'Session differs from expected')

        #
        # CPO stops the session
        #

        # Clean out the previous session which would be completed and CDR created
        Cdr.objects.filter(session_id='FI*CPO*S*MOCK-1').delete()

        cdr_count_before = Cdr.objects.all().count()

        with time_machine.travel(faketime + timedelta(minutes=23), tick=False):
            response = stop_transaction(dict(session_id='FI*CPO*S*MOCK-1', stop_timestamp=timezone.now()))

        self.assertEqual(response.status_code, 200, f'CPO stop_transaction is expected to succeed: {response.data}')
        cdr_count_after = Cdr.objects.all().count()

        self.assertEqual(cdr_count_after - cdr_count_before, 1,
                         'There should be one new CDR after stopping a session')

        # ic(recursive_sort_dict(response.data.get('session')), recursive_sort_dict(StopTransactionResponses.stop3.get('session')))
        # ic(recursive_sort_dict(response.data.get('charge_detail_record')), recursive_sort_dict(StopTransactionResponses.stop3.get('charge_detail_record')))
        self.assertTrue(compare_dicts_recursively(response.data, StopTransactionResponses.stop3),
                        'stop_transaction response differs from expected')

        # Check that the Session looks correct

        session = Session.objects.get(internal_reference='MY-INTERNAL-REFERENCE-2')
        self.assertEqual(session.status, Session.COMPLETED, 'Session should be COMPLETED after CPO stop_transaction')
        self.assertEqual(session.kwh, Decimal('123.450'))
        cdr = Cdr.objects.get(session_id=session.uid)
        self.assertEqual(cdr.billed_to, session.billed_to)
        self.assertEqual(cdr.authorization_reference, session.authorization_reference)

        # Try to end the same Session again, should fail
        response = stop_transaction(dict(internal_reference='MY-INTERNAL-REFERENCE-2', stop_timestamp=timezone.now()))
        cdr_count_after = Cdr.objects.all().count()
        self.assertEqual(cdr_count_after - cdr_count_before, 1,
                         'There should be only one new CDR after trying to stop a session twice')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT,
                         f'A duplicate CPO stop_transaction is expected to fail: {response.data}')

        # Check the invoice creation
        with time_machine.travel(faketime + timedelta(days=1), tick=False):
            invoice = create_invoice(session.credentials)  # Should collect CDRs until the current date
            self.assertDictEqual(asdict(invoice), {'currency': 'EUR',
                                                   'total_cost_excl_vat': {'total_cost_excl_vat__sum': 61.73},
                                                   'total_cost_incl_vat': {'total_cost_incl_vat__sum': 76.54},
                                                   'total_energy': {'total_energy__sum': 123.45},
                                                   'transactions': 1},
                                 "The invoice resulting from RFID charging case differs from expected")


def put_session_data(data, create_authorization=True):
    request = api_factory.post(reverse('session-list'))
    request.data = data
    request.user = get_fake_admin()
    request.credentials = Credentials.objects.first()
    request.accepted_media_type = 'text/html'  # To get the detail_url in the response
    request.version = '2.2.1'
    party = Party(data.get('country_code'), data.get('party_id'))
    assert party
    request.ocpi_party = create_credentialsrole(party, business_name='Test name', website='', role=OcpiRolesEnum.CPO,
                                                credentials=request.credentials)
    assert request.ocpi_party
    if create_authorization:
        authorization_reference = data.get('authorization_reference', '')
        Authorization.objects.create(authorization_reference=authorization_reference)
    return SessionViewSet.put(request)


class TestPutSession(TestCase):
    fixtures = ['ocpi22/data/test-database-cpo-api.json']

    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://fakehost/stop/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
               'callback-invoicing_url': 'http://localhost/invoice/{uid}/',
           }.get(x))
    @patch('ocpi22.webhooks.requests.post')
    def test_put_session_with_charging_periods(
            self,
            webhook_post_mock: Mock,
            _redis_store_mock: Mock,
    ):
        # First I decided to reject Session PUT if there is no matching Authorization on the MSP end,
        # But I realized that such Sessions need to be sorted by hand afterwards
        #
        # response = put_session_data(SessionData.meter_values_1, create_authorization=False)
        # self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
        #                  'Creating a session with no authorization from the MSP should fail')
        # sessions = Session.objects.filter(authorization_reference='FI*001-AUTH-REFERENCE')
        # assert sessions.count() == 1
        # sessions.delete()

        with time_machine.travel(faketime, tick=False):
            response = put_session_data(SessionData.meter_values_1)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED,
                         'Creating a session with ChargingPeriods should succeed')
        calls = webhook_post_mock.call_args_list
        self.assertTrue(compare_dicts_recursively(calls[0].kwargs.get('json'), SessionData.meter_values_1_webhook))
        webhook_post_mock.assert_called_once()

    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-start_transaction_url': 'http://fakehost/start/{evse_id}/',
               'callback-stop_transaction_url': 'http://fakehost/stop/{evse_id}/',
               'callback-session_url': 'http://localhost/session/{uid}/',
               'callback-invoicing_url': 'http://localhost/invoice/{uid}/',
           }.get(x))
    @patch('ocpi22.webhooks.requests.post')
    def test_put_session_to_wrong_evse(
            self,
            webhook_post_mock: Mock,
            _redis_store_mock: Mock,
    ):
        with patch('ocpi22.ocpi.api.fetch_location') as mock_fetch_location:
            mock_fetch_location.return_value = None
            response = put_session_data(SessionData.wrong_evse)
            mock_fetch_location.assert_called_once()

            # Todo: do the actual test

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'Creating a session with wrong EVSE should fail gracefully')
        webhook_post_mock.assert_not_called()


def meter_values(data):
    credentials = Credentials.objects.first()
    request = api_factory.post(reverse('chargepoint-meter-values'))
    request.data = data
    request.accepted_media_type = 'text/html'  # To get the detail_url in the response
    request.version = '2.2.1'
    request.credentials = credentials
    with patch('ocpi22.cpo.api.redis_store'):
        return ChargePointViewSet().meter_values(request)


def start_transaction(data):
    start_url = reverse('chargepoint-start-transaction')
    start_request = api_factory.post(start_url)
    start_request.data = data
    start_request.accepted_media_type = 'text/html'  # To get the detail_url in the response
    start_request.version = '2.2.1'
    return ChargePointViewSet().start_transaction(start_request)


def stop_transaction(data):
    url = reverse('chargepoint-stop-transaction')
    stop_request = api_factory.post(url)
    stop_request.data = data
    stop_request.accepted_media_type = 'text/html'  # To get the detail_url in the response
    stop_request.version = '2.2.1'
    return ChargePointViewSet().stop_transaction(stop_request)


def authorize(data):
    authorize_url = reverse('chargepoint-authorize')
    cpo_request = api_factory.post(authorize_url)
    cpo_request.data = data
    cpo_request.accepted_media_type = 'text/html'  # To get the detail_url in the response
    cpo_request.version = '2.2.1'
    return ChargePointViewSet().authorize(cpo_request)


class TestMspApi(TestCase):
    fixtures = ['ocpi22/data/test-database-msp-api.json']
    maxDiff = None

    accepted_result = {
        "data": {
            "result": "ACCEPTED",
            "timeout": 123,
            "message": [
                {
                    "language": "EN",
                    "text": "Preparing to charge"
                }
            ]
        }
    }

    def setUp(self) -> None:
        self.user = User.objects.create_user('eki')

    @time_machine.travel(faketime, tick=True)
    @patch('ocpi22.ocpi.util.uuid.uuid4',
           return_value=mock_uuid4())
    @patch('ocpi22.webhooks.requests.post',
           return_value=FakeResponse(200, accepted_result)
           )
    @patch('ocpi22.webhooks.requests.post')
    def test_app_charging(self,
                          _webhook_post_mock: Mock,
                          requests_post_mock: Mock,
                          _uuid4_mock: Mock):
        data = {
            "location_id": "HELSINKI-1",
            "evse_uid": "HELSINKI-3",
            "connector_id": "1",
            "contract_id": "CONTRACT-123",
            "internal_reference": "REFERENCE-123"
        }

        # See that Account is created automatically
        response = start_charging(data, self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         f'Expecting charging to start without specifically creating an account {response.data}')

        # Create an account with insufficient balance
        account = self.user.accounts.first()  # There should be an automatically created Account
        new_balance = Decimal("0.80")
        account.deposit(new_balance)
        settings.REQUIRE_WALLET_BALANCE = True

        # Try charging without enough money
        response = start_charging(data, self.user, version='2.2')
        # ic(response, response.data)
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED,
                         'Charging should fail due to insufficient account balance')

        # Ok, more money
        self.assertEqual(account.balance, new_balance, "First account deposit not working as expected")
        self.assertEqual(account.transactions.count(), 1, 'There should be one Transaction on Account')
        account.deposit(Decimal("50") - account.balance)
        self.assertEqual(account.transactions.count(), 2, 'There should be two Transactions on Account')
        self.assertEqual(account.balance, Decimal("50"), "Second account deposit not working as expected")

        response = start_charging(data, self.user)

        # ic(recursive_sort_dict(response.data), recursive_sort_dict(self.accepted_result.get('data')))
        self.assertEqual(response.data, self.accepted_result.get('data'),
                         'Response from CPO for START_SESSION differs from expected')
        args, kwargs = requests_post_mock.call_args
        self.assertEqual(args, ('http://fakehost/command/START_SESSION',),
                         'URL for CPO Command START_SESSION differs from expected')
        expected_data_sent = {'headers': {'Authorization': 'Token VEhFSVJT',
                                          'OCPI-from-country-code': 'FI',
                                          'OCPI-from-party-id': 'MSP',
                                          'OCPI-to-country-code': 'FI',
                                          'OCPI-to-party-id': 'CPO',
                                          'content-type': 'application/json'},
                              'json': {'authorization_reference': 'REFERENCE-123',
                                       'evse_uid': 'HELSINKI-3',
                                       'location_id': 'HELSINKI-1',
                                       'response_url': 'http://testserver.test/ocpi/2.2.1/commands/COMMAND_RESULT/start/REFERENCE-123',
                                       'token': dict([('country_code', 'FI'),
                                                      ('party_id', 'MSP'),
                                                      ('uid', 'FI*MSP*T*APP*MOCK-1'),
                                                      ('type', 'APP_USER'),
                                                      ('contract_id', 'CONTRACT-123')])},
                              'timeout': 25
                              }
        # ic(recursive_sort_dict(kwargs), recursive_sort_dict(expected_data_sent))
        self.assertTrue(compare_dicts_recursively(kwargs, expected_data_sent),
                        'START_SESSION Command sent to CPO differs from expected')

        settings.REQUIRE_WALLET_BALANCE = False

        data["max_price"] = Decimal(30)
        requests_post_mock.reset_mock()

        response = start_charging(data, self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         'Expecting charging to start succesfully')
        args, kwargs = requests_post_mock.call_args
        self.assertEqual(args, ('http://fakehost/command/START_SESSION',),
                         'URL for CPO Command START_SESSION differs from expected')
        self.assertTrue(compare_dicts_recursively(kwargs, {'headers': {'Authorization': 'Token VEhFSVJT',
                                                                       'OCPI-from-country-code': 'FI',
                                                                       'OCPI-from-party-id': 'MSP',
                                                                       'OCPI-to-country-code': 'FI',
                                                                       'OCPI-to-party-id': 'CPO',
                                                                       'content-type': 'application/json'},
                                                           'json': {'authorization_reference': 'REFERENCE-123',
                                                                    # 'connector_id': '1',  # OCPI 2.2 doesn't support this in the remote start command
                                                                    'evse_uid': 'HELSINKI-3',
                                                                    'location_id': 'HELSINKI-1',
                                                                    'response_url': 'http://testserver.test/ocpi/2.2.1/commands/COMMAND_RESULT/start/REFERENCE-123',
                                                                    'token': OrderedDict([('country_code', 'FI'),
                                                                                          ('party_id', 'MSP'),
                                                                                          (
                                                                                              'uid',
                                                                                              'FI*MSP*T*APP*MOCK-1'),
                                                                                          ('type', 'APP_USER'),
                                                                                          ('contract_id',
                                                                                           'CONTRACT-123')])},
                                                           'timeout': 25
                                                           },
                                                  'START_SESSION Command sent to CPO differs from expected'))

        #
        # Try bad values for stop_charging()
        #

        response = stop_charging(dict(token_id=1, session_id=2))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'Response with bad parameters is expected to return HTTP 400')
        #
        # Stop an existing session
        #

        response = stop_charging(dict(session_id=12345))
        self.assertEqual(response.status_code, status.HTTP_200_OK,
                         'Call is expected to succeed')
        self.assertTrue(compare_dicts_recursively(response.data, self.accepted_result.get('data')),
                        'Response from CPO for STOP_SESSION differs from expected')

    #
    # This was a bad idea, since there doesn't seem to be a way to sync charging sessions between parties without using
    # the authorization_reference
    #
    # @time_machine.travel(faketime, tick=True)
    # @patch('ocpi22.ocpi.util.uuid.uuid4',
    #        return_value=mock_uuid4())
    # @patch('ocpi22.webhooks.requests.post',
    #        return_value=FakeResponse(200, accepted_result)
    #        )
    # @patch('ocpi22.webhooks.requests.post')
    # def test_without_authorization_reference(self,
    #                       _webhook_post_mock: Mock,
    #                       requests_post_mock: Mock,
    #                       _uuid4_mock: Mock):
    #     data = {
    #         "location_id": "HELSINKI-1",
    #         "evse_uid": "HELSINKI-3",
    #         "connector_id": "1",
    #         "contract_id": "CONTRACT-123"
    #     }
    #
    #     with patch('ocpi22.msp.api.generate_auth_reference') as generate_auth_reference_mock:
    #         # Let's leave the authorization_reference empty, since that is allowed in OCPI 2.2
    #         generate_auth_reference_mock.return_value = None
    #         response = start_charging(data, self.user)
    #         generate_auth_reference_mock.assert_called_once()
    #
    #     self.assertTrue(compare_dicts_recursively(response.data, self.accepted_result.get('data')),
    #                     'Response from CPO for START_SESSION differs from expected')
    #     args, kwargs = requests_post_mock.call_args
    #     self.assertEqual(args, ('http://fakehost/command/START_SESSION',),
    #                      'URL for CPO Command START_SESSION differs from expected')
    #     expected_data_sent = {'headers': {'Authorization': 'Token VEhFSVJT',
    #                                       'OCPI-from-country-code': 'FI',
    #                                       'OCPI-from-party-id': 'MSP',
    #                                       'OCPI-to-country-code': 'FI',
    #                                       'OCPI-to-party-id': 'CPO',
    #                                       'content-type': 'application/json'},
    #                           'json': {'authorization_reference': None,
    #                                    # 'connector_id': '1', # OCPI 2.2 should exclude the connector_id from remote command
    #                                    'evse_uid': 'HELSINKI-3',
    #                                    'location_id': 'HELSINKI-1',
    #                                    'response_url': 'http://testserver.test/ocpi/2.2.1/commands/COMMAND_RESULT/start/None',
    #                                    'token': dict([('country_code', 'FI'),
    #                                                   ('party_id', 'MSP'),
    #                                                   ('uid', 'FI*MSP*T*APP*MOCK-1'),
    #                                                   ('type', 'APP_USER'),
    #                                                   ('contract_id', 'CONTRACT-123')])},
    #                           'timeout': 25
    #                           }
    #     self.assertTrue(compare_dicts_recursively(kwargs, expected_data_sent),
    #                     'START_SESSION Command sent to CPO differs from expected')


def start_charging(data, user, version='2.2.1'):
    request = api_factory.post(reverse('roaming-start-charging'))
    request.data = data
    request.user = user
    request.version = version
    return MspRoamingViewSet().start_charging(request)


def stop_charging(data):
    request = api_factory.post(reverse('roaming-stop-charging'))
    request.data = data
    return MspRoamingViewSet().stop_charging(request)


def start_session(data, user):
    request = api_factory.post(reverse('commands-start-session'), sender=Party('FI', 'MSP'))
    request.data = data
    request.user = user
    return CommandsViewSet.start_session(request)


def stop_session(data, user):
    request = api_factory.post(reverse('commands-stop-session'), sender=Party('FI', 'MSP'))
    request.data = data
    request.user = user
    return CommandsViewSet().stop_session(request)


def send_command_result(data, url, command, command_id):
    request = api_factory.post(url)
    request.data = data
    return CommandsViewSet().command_result(request, command, command_id)


class TestMspMap(TestCase):
    fixtures = ['ocpi22/data/test-database-msp-api.json']
    maxDiff = None

    expected_map_result = {"features": [{"geometry": {"coordinates": [30.0, 60.0], "type": "Point"},
                                         "properties": {"evses:0:connectors:0:power": None,
                                                        "evses:0:connectors:0:price": "0,50\u20ac/kWh",
                                                        "evses:0:connectors:0:standard": "TESLA_S",
                                                        "evses:0:connectors:0:uid": "3050",
                                                        "evses:0:evse_id": "FI*TSL*EHELSINKI1",
                                                        "evses:0:status": "AVAILABLE", "evses:0:uid": "HELSINKI-1",
                                                        "evses:1:connectors:0:power": None,
                                                        "evses:1:connectors:0:price": "",
                                                        "evses:1:connectors:0:standard": "TESLA_S",
                                                        "evses:1:connectors:0:uid": "1",
                                                        "evses:1:evse_id": "FI*TSL*EHELSINKI2",
                                                        "evses:1:status": "AVAILABLE", "evses:1:uid": "HELSINKI-2",
                                                        "evses:2:connectors:0:power": None,
                                                        "evses:2:connectors:0:price": "0,50\u20ac/kWh",
                                                        "evses:2:connectors:0:standard": "TESLA_S",
                                                        "evses:2:connectors:0:uid": "1",
                                                        "evses:2:evse_id": "FI*TSL*EHELSINKI3",
                                                        "evses:2:status": "AVAILABLE", "evses:2:uid": "HELSINKI-3",
                                                        "location:address": "Helsinki 12", "location:city": "Helsinki",
                                                        "location:connectors_available:TESLA_S": 3,
                                                        "location:country": "FIN",
                                                        "location:name": "Helsinki Supercharger",
                                                        "location:uid": "HELSINKI-1"}, "type": "Feature"}],
                           "type": "FeatureCollection"}

    def test_map(self):
        response = self.client.get(reverse('map-locations'))
        self.assertDictEqual(response.data, self.expected_map_result,
                             'The charge point GeoJSON differs from expected')


def msp_authorize(loser_token_id):
    request = api_factory.post(reverse('token-authorize', args=[loser_token_id]))
    request.data = dict()
    request.user = get_fake_admin()
    request.accepted_media_type = 'text/html'  # To get the detail_url in the response
    request.version = '2.2.1'
    return TokenViewSet().authorize(request, loser_token_id)


class TestMspUserApi(TestCase):
    fixtures = ['ocpi22/data/test-database-msp-api.json']
    maxDiff = None
    userdata = dict(email='erkki.tapola@pohdinto.com', firstname='Erkki',
                    lastname='Tapola', telephone='+1234567890123456789',
                    vehicle='artega-karo-range-plus', password='qwerty', confirm='qwerty')

    def setUp(self) -> None:
        os.environ['TEST'] = "1"

    def _create_user(self, **data):
        return send_create_user(data)

    @patch('cars.cars.get_json', return_value=test_data.cars_json)
    def test_create_user(self, _get_json_mock: Mock):
        userdata = self.userdata
        # Make sure the user doesn't already exist
        self.assertFalse(User.objects.filter(email=userdata.get('email')).count())

        # Create a user successfully
        response = self._create_user(**userdata)
        expected_response_data = userdata.copy()
        expected_response_data.pop('password')
        expected_response_data.pop('confirm')
        self.assertDictEqual(response.data, expected_response_data,
                             'Response for creating a user differs from expected')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, 'Creating a user should result in HTTP 201')
        user = User.objects.get(username=userdata.get('email'))  # Username should equal email address
        self.assertEqual(user.first_name, userdata.get('firstname'))
        self.assertEqual(user.accounts.count(), 1, 'There should be one account created per user')

        # Try to create a duplicate user
        response = self._create_user(**userdata)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT,
                         'Creating a duplicate user should result in HTTP 409')

    def set_balance(self, amount):
        self.account.transactions.all().delete()
        self.account.deposit(amount)
        self.assertEqual(self.account.balance, amount, 'Account balance differs from expected after a deposit')

    def setUp(self):
        params = dict(email='rich@money.com', password='hello', confirm='hello')
        initial_balance = 70
        response = self._create_user(**params)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(username=params.get('email'), email=params.get('email'))
        # Check that account is created automatically and with zero balance
        self.assertEquals(user.accounts.count(), 1, "A new user doesn't get an account automatically")
        account = user.accounts.first()
        self.assertEquals(account.balance, Decimal("0.0"), 'User has some money out of nowhere')

        # Clear out any Sessions which prevent new charging sessions
        Session.objects.filter(status__in=[Session.PENDING, Session.ACTIVE]).update(status=Session.COMPLETED)

        # Create a Session
        evse = Evse.objects.all()[0]
        uid = 'test-transactions'
        self.token_uid = 'EKI1'
        credentials = Credentials.objects.first()

        with patch('ocpi22.tokens.auth.authorize_token') as authorize_token_mock:
            party = Party('FI', 'TST')
            authorize_token_mock.return_value = TokenAuthorization(
                    allowed='ALLOWED',
                    info=MessageTexts.get('TOKEN_ACCEPTED'),
                    token=AdhocToken(True, party, self.token_uid, TokenType.AD_HOC_USER),
                    party=party,
                    authorization_reference='1234567890',
                    auth_method=Session.AUTH_REQUEST,
                )
            session = create_session(
                uid=uid, evse_uid=evse, location_id=evse.location, connector_id=evse.connectors.all().first().uid,
                token_id=self.token_uid, billed_to='FI*MSP', start_kwh=0.0, stop_kwh=100.0,
                session_status=Session.ACTIVE, credentials=credentials, ocpi_master=credentials.roles.first()
            )
            authorize_token_mock.assert_called_once()
            self.assertTrue(bool(session))
            session.calculate_price()
            session.save()

        self.user = user
        self.account = account
        self.initial_balance = initial_balance
        self.session = session

    @patch('ocpi22.tokens.auth.ocpi_post', side_effect=[make_json_response(accept_authorization)])
    @patch('ocpi22.ocpi.api.requests.post', side_effect=[make_json_response(accept_authorization_msp)])
    @patch('ocpi22.util.redis_store.get',
           side_effect=lambda x: {
               'callback-authorize_url': '',
               'callback-session_url': 'http://localhost/session/{uid}/',
           }.get(x))
    @patch('ocpi22.ocpi.util.logging')  # There are some conflicts with atomic transactions when logging to mysql
    def test_cdrs_and_transactions(self, _mocked_logging: Mock, _mocked_redis_store: Mock, _mocked_requests_post: Mock,
                                   _mocked_ocpi_post: Mock):
        # Try to authorize charging with no money in account
        with patch('django.conf.settings.REQUIRE_WALLET_BALANCE', True):
            token_id = 'EKI1'
            Token.objects.filter(uid=token_id).update(customer=self.user)
            response = msp_authorize(token_id)
            # Todo: Test authorize also with Location and Evses
            self.assertEquals(response.status_code, status.HTTP_401_UNAUTHORIZED,
                              'Charging should not be authorized if account is empty')
            self.assertEquals(response.data.get('data').get('allowed'), 'NO_CREDIT',
                              'Declined authorization should have allowed status "NO_CREDIT"')
        #
        # Try an RFID
        #

        self.set_balance(self.initial_balance)

        with patch('django.conf.settings.REQUIRE_WALLET_BALANCE', True), \
                patch('django.conf.settings.USE_ACCOUNTS', True):
            Token.objects.filter(uid=self.token_uid).update(customer=self.user)
            cdr = Cdr.create_based_on_session(self.session)
            serializer = CdrSerializer(instance=cdr)
            self.assertEqual([cdr.total_cost_incl_vat, cdr.total_cost_excl_vat], [62.0, 50.0],
                             'CDR cost seems to be off')

            # Cleanup for next test
            cdr.delete()

            response = post_cdr(CdrMessages.test_transactions_rfid)
            self.assertEquals(response.status_code, 201, 'CDR PUT seems to have failed')
            self.assertEqual(self.account.balance, self.initial_balance - cdr.total_cost_incl_vat,
                             'Account balance differs from expected after a charging session')

        # Try to put a duplicate CDR

        response = post_cdr(CdrMessages.test_transactions_rfid)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST,
                         'A duplicate CDR PUT is expected to fail')
        msg = response.data.get('status_message')
        self.assertTrue('already exists' in msg,
                        f'A duplicate CDR PUT is expected to fail: {msg}')

    def test_cdrs_and_transactions2(self):
        # Charge using the mobile app and an APP_TOKEN

        self.set_balance(self.initial_balance)

        user = self.user
        account = self.account
        with patch('django.conf.settings.USE_ACCOUNTS', True):
            app_token_id = CdrMessages.test_transactions_app_id.get('cdr_token').get('uid')
            self.session.cdr_token_uid = app_token_id
            self.session.save()
            initial_balance = 70
            account.app_token_id = app_token_id
            account.deposit(initial_balance)
            account.save()
            previous_balance = account.balance
            assert account.app_token_id == app_token_id, 'Account app_token_id not set'
            Account.objects.filter(app_token_id=self.session.cdr_token_uid).first()

            response = post_cdr(CdrMessages.test_transactions_app_id)
            cost = Decimal("6.20")
            self.assertEquals(response.status_code, 201, 'CDR PUT seems to have failed')
            self.assertEqual(account.balance, previous_balance - cost,
                             'Account balance differs from expected after a charging session')


def send_create_user(data):
    request = api_factory.post(reverse('user-register'))
    request.data = data
    return UserViewSet().register(request)


@dataclass
class FakeUser:
    username: str
    is_staff: bool
    is_superuser: bool


def get_fake_admin():
    return FakeUser('admin', True, True)


def post_cdr(data):
    request = api_factory.post(reverse('cdr-list'))
    request.data = data
    request.user = get_fake_admin()
    request.version = '2.2.1'
    return CdrViewSet().post(request)


class TestBillingList(TestCase):
    fixtures = ['ocpi22/data/credentials.json']

    def test_empty_billing_list(self):
        request = api_factory.get(reverse('billing-list'))
        request.user = get_fake_admin()
        request.query_params = {}
        response = InvoiceReportViews().session_list(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data,
                         OrderedDict([('count', 0), ('next', None), ('previous', None), ('results', [])]))


class TestOCPIAuthentication(TestCase):
    fixtures = ['ocpi22/data/credentials-auth-test.json']

    @staticmethod
    def _make_test_request(sender: Party, to: Party, hub: Optional[Party] = None):
        request = api_factory.post('http://localhost:8101/anyurl/')
        from ocpi22.routing import find_credentials
        credentials = find_credentials(hub) if hub else find_credentials(sender)
        request.headers = make_headers(credentials.ours_base64(), to=to, sender=sender)
        return request, credentials.ours_base64()

    def test_hub_routed_message(self):
        hub_party = Party('FI', 'HBB')
        msp_party = Party('FI', 'MSP')
        our_party = get_our_party(OcpiRolesEnum.CPO)

        # Message routed trough a hub
        request, token_base64 = self._make_test_request(sender=msp_party, to=our_party, hub=hub_party)
        self.assertTrue(check_auth_token(request, token_base64))
        self.assertEqual(
            request.credentials,
            Credentials.objects.get(roles__country_code=hub_party.country_code, roles__party_id=hub_party.party_id)
        )
        self.assertEqual(request.ocpi_party, get_credentialsrole(None, msp_party))

        # Message directly from sender to us
        request, token_base64 = self._make_test_request(sender=msp_party, to=our_party)
        self.assertTrue(check_auth_token(request, token_base64))
        self.assertEqual(
            request.credentials,
            Credentials.objects.get(roles__country_code=msp_party.country_code, roles__party_id=msp_party.party_id)
        )
        self.assertEqual(request.ocpi_party, get_credentialsrole(request.credentials, msp_party))

        # Message from hub to us through msp, this should definitely fail
        request, token_base64 = self._make_test_request(sender=hub_party, to=our_party, hub=msp_party)
        with self.assertRaises(NotAuthenticated):
            check_auth_token(request, token_base64)
        self.assertFalse(request.credentials)
        self.assertFalse(request.ocpi_party)

        # Wrongly formatted and wrong tokens
        with self.assertRaises(NotAuthenticated):
            check_auth_token(request, 'WRONGTOKEN')
        with self.assertRaises(NotAuthenticated):
            check_auth_token(request, 'AB==')


# Todo: Hub to relay Evse PATCH to everybody as PATCH (I think is't DONE, needs testing)
