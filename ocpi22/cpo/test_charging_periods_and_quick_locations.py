import doctest
import sys
from collections import OrderedDict
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
from unittest.mock import patch

import geopy
import pytz
import time_machine
from django.db import connection, reset_queries
from django.test import TestCase

from django.contrib.auth.models import AnonymousUser
from icecream import ic
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from urllib3.exceptions import ConnectTimeoutError

from ocpi22.cpo.test_data import LocationData
from ocpi22.ocpi.serializers import SessionSerializer
from ocpi22.routing import find_route
from django.conf import settings
from ocpiconnector.testutil import compare_dicts_recursively, simulate_surrounding_world
from ocpiconnector.util import Timer
from util import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.cpo import test_data
from ocpi22.cpo.api import LocationQuickViewSet
from ocpi22.cpo.serializers import LocationQuickSerializer
from ocpi22.cpo.tariff import TariffQuickViewSet
from ocpi22.models.location import Location
from ocpi22.models.session import Session

api_factory = APIRequestFactory()
faketime = datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc)


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("ocpi22.cpo.util"))
    return tests


class TestQuickLocations(TestCase):
    fixtures = [
        "ocpi22/data/credentials-2.json",
        "ocpi22/cpo/database-dumps/tariffs.json",
    ]
    maxDiff = 99999

    @simulate_surrounding_world
    def test_quick_location_with_evses_and_connectors(self, simulation):
        #
        # Create Location
        #

        with time_machine.travel(faketime, tick=False):
            response = put_location(
                test_data.LocationData.location1, reverse("quick-location-list")
            )
        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            "Expecting Location to be created successfully",
        )
        location = Location.get_if_exists(
            uid=test_data.LocationData.location1.get("id")
        )
        data = LocationQuickSerializer(instance=location).data
        assert dict(data) == LocationData.quick_location_with_evses_and_connectors, \
            "New Location data differs from expected"

        #
        # Update Location
        #

        data_update = test_data.LocationData.location_update1
        with time_machine.travel(faketime, tick=False):
            response = patch_location(
                data_update, reverse("quick-location-list")
            )
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            "Expecting Location to be updated successfully",
        )
        location = Location.get_if_exists(
            uid=data_update.get("id")
        )
        data = LocationQuickSerializer(instance=location).data
        assert dict(data) == LocationData.quick_location_with_evses_and_connectors_update, \
            "Updated Location data differs from expected"

    def test_quick_tariff(self):
        test_cases = [
            dict(
                data={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 1.0,
                    "price_per_min": 2.0,
                    "price_flat": 3.0,
                    "vat": 24.0,
                },
                status=status.HTTP_201_CREATED,
            ),
            dict(
                data={
                    "id": "ALLTYPES",
                    "currency": "EUR",
                    "price_per_kwh": 1.0,
                    "price_per_min": 2.0,
                    "price_flat": 3.0,
                    "vat": 0.24,
                },
                status=status.HTTP_400_BAD_REQUEST,
                expected_result={
                    "vat": [
                        ErrorDetail(
                            string="VAT should be the percentage (0-100), not the decimal presentation",
                            code="invalid",
                        )
                    ]
                },
            ),
            dict(
                method="PATCH",
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
                    "vat": 24,
                },
            ),
            dict(
                method="PATCH",
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
                    "vat": 0,
                },
            ),
            dict(
                method="PATCH",
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
                    "vat": 0,
                },
            ),
        ]
        for case in test_cases:
            with self.subTest(case=case):
                data = case["data"]
                if case.get("method") == "PATCH":
                    response = send_patch(
                        data, reverse("quick-tariff-list"), TariffQuickViewSet
                    )
                else:
                    response = put(
                        data, reverse("quick-tariff-list"), TariffQuickViewSet
                    )
                self.assertEqual(
                    response.status_code,
                    case.get("status", status.HTTP_200_OK),
                    "Quick Tariff creation/update response status differs from expected",
                )
                self.assertTrue(
                    compare_dicts_recursively(
                        response.data, case.get("expected_result", data)
                    ),
                    "Quick Tariff creation/update response data differs from expected",
                )

        # The below needs some work
        # response = get(reverse('quick-tariff-list'), TariffQuickViewSet)
        # ic(response.status_code, response.data)


class TestChargingPeriods(TestCase):
    fixtures = [
        "ocpi22/data/credentials-2.json",
        "ocpi22/cpo/database-dumps/complex-tariffs-1.json",
        "ocpi22/cpo/database-dumps/tariffs-time-weekday.json",
    ]
    maxDiff = None

    @simulate_surrounding_world
    def test_tariff_change(self, simulation):
        meter_values_data = (
            # (kWh, SoC, timestamp)
            (
                2,
                52,
                datetime(2022, 12, 25, 21, 55, tzinfo=pytz.utc),  # Weekday 6 = Sunday
                {  # Check send_update() parameters for the first call
                    "kwh": "2.000",
                    "last_updated": "2022-12-25T21:55:00Z",
                    "total_cost": {"excl_vat": 0.6, "incl_vat": 0.74},
                    "charging_periods": [
                        OrderedDict(
                            [
                                ("start_date_time", "2022-12-25T21:55:00Z"),
                                ("tariff", "WEEKENDS"),
                                (
                                    "dimensions",
                                    [
                                        OrderedDict(
                                            [("type", "ENERGY"), ("volume", "2.0000")]
                                        ),
                                        OrderedDict(
                                            [
                                                ("type", "STATE_OF_CHARGE"),
                                                ("volume", "52.0000"),
                                            ]
                                        ),
                                    ],
                                ),
                            ]
                        )
                    ],
                },
                {
                    "internal_reference": None,
                    "now_kwh": 2.0,
                    "power": None,
                    "price": "0,74zł",
                    "session_id": "FI*000*S*B58DDC4D3B304A47AD623C22147",
                    "soc": 52.0,
                    "start_kwh": 0.0,
                    "status_text": "Session updated",
                    "total_kwh": Decimal("2.000"),
                },
                None,
            ),
            (
                7,
                57,
                datetime(2022, 12, 25, 21, 58, tzinfo=pytz.utc),
                None,
                None,
                None,
            ),  # Weekday 6 = Sunday
            # The ChargingPeriod should change here, and the first one should stop at the time the next one starts
            (
                10,
                60,
                datetime(2022, 12, 25, 22, 1, tzinfo=pytz.utc),
                None,
                None,
                None,
            ),  # Weekday 0 = Monday
            (13, 63, datetime(2022, 12, 25, 22, 3, tzinfo=pytz.utc), None, None, None),
            (15, 65, datetime(2022, 12, 25, 22, 5, tzinfo=pytz.utc), None, None, None),
            (
                45,
                95,
                datetime(
                    2022, 12, 26, 6, 0, tzinfo=pytz.utc
                ),  # This should cause a third ChargingPeriod to be created
                None,
                None,
                None,
            ),
            (
                50,
                99,
                datetime(2022, 12, 26, 6, 30, tzinfo=pytz.utc),
                {
                    "charging_periods": [
                        OrderedDict(
                            [
                                ("start_date_time", "2022-12-25T21:55:00Z"),
                                ("tariff", "WEEKENDS"),
                                (
                                    "dimensions",
                                    [
                                        OrderedDict(
                                            [("type", "ENERGY"), ("volume", "7.0000")]
                                        ),
                                        OrderedDict(
                                            [
                                                ("type", "STATE_OF_CHARGE"),
                                                ("volume", "57.0000"),
                                            ]
                                        ),
                                        OrderedDict(
                                            [("type", "TIME"), ("volume", "0.1000")]
                                        ),
                                    ],
                                ),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("start_date_time", "2022-12-25T22:01:00Z"),
                                ("tariff", "WEEKDAYS"),
                                (
                                    "dimensions",
                                    [
                                        OrderedDict(
                                            [("type", "ENERGY"), ("volume", "8.0000")]
                                        ),
                                        OrderedDict(
                                            [
                                                ("type", "STATE_OF_CHARGE"),
                                                ("volume", "65.0000"),
                                            ]
                                        ),
                                        OrderedDict(
                                            [("type", "TIME"), ("volume", "7.9833")]
                                        ),
                                    ],
                                ),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("start_date_time", "2022-12-26T06:00:00Z"),
                                ("tariff", "WEEKDAYS"),
                                (
                                    "dimensions",
                                    [
                                        OrderedDict(
                                            [("type", "ENERGY"), ("volume", "35.0000")]
                                        ),
                                        OrderedDict(
                                            [
                                                ("type", "STATE_OF_CHARGE"),
                                                ("volume", "99.0000"),
                                            ]
                                        ),
                                        OrderedDict(
                                            [("type", "TIME"), ("volume", "0.5000")]
                                        ),
                                    ],
                                ),
                            ]
                        ),
                    ],
                    "kwh": "50.000",
                    "last_updated": "2022-12-26T06:30:00Z",
                    "total_cost": {"excl_vat": 22.8, "incl_vat": 28.27},
                },
                {
                    "internal_reference": None,
                    "now_kwh": 50.0,
                    "power": None,
                    "price": "28,27zł",
                    "session_id": "FI*000*S*B58DDC4D3B304A47AD623C22147",
                    "soc": 99.0,
                    "start_kwh": 0.0,
                    "status_text": "Session updated",
                    "total_kwh": Decimal("50.000"),
                },
                {
                    "country_code": "FI",
                    "party_id": "000",
                    "id": "FI*000*S*B58DDC4D3B304A47AD623C22147",
                    "start_date_time": "2022-12-14T17:03:19Z",
                    "kwh": 50.0,
                    "charging_periods": [
                        OrderedDict(
                            [
                                ("start_date_time", "2022-12-25T21:55:00Z"),
                                ("tariff", "WEEKENDS"),
                                (
                                    "dimensions",
                                    [
                                        OrderedDict(
                                            [("type", "ENERGY"), ("volume", "7.0000")]
                                        ),
                                        OrderedDict(
                                            [
                                                ("type", "STATE_OF_CHARGE"),
                                                ("volume", "57.0000"),
                                            ]
                                        ),
                                        OrderedDict(
                                            [("type", "TIME"), ("volume", "0.1000")]
                                        ),
                                    ],
                                ),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("start_date_time", "2022-12-25T22:01:00Z"),
                                ("tariff", "WEEKDAYS"),
                                (
                                    "dimensions",
                                    [
                                        OrderedDict(
                                            [("type", "ENERGY"), ("volume", "8.0000")]
                                        ),
                                        OrderedDict(
                                            [
                                                ("type", "STATE_OF_CHARGE"),
                                                ("volume", "65.0000"),
                                            ]
                                        ),
                                        OrderedDict(
                                            [("type", "TIME"), ("volume", "7.9833")]
                                        ),
                                    ],
                                ),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("start_date_time", "2022-12-26T06:00:00Z"),
                                ("tariff", "WEEKDAYS"),
                                (
                                    "dimensions",
                                    [
                                        OrderedDict(
                                            [("type", "ENERGY"), ("volume", "35.0000")]
                                        ),
                                        OrderedDict(
                                            [
                                                ("type", "STATE_OF_CHARGE"),
                                                ("volume", "99.0000"),
                                            ]
                                        ),
                                        OrderedDict(
                                            [("type", "TIME"), ("volume", "0.5000")]
                                        ),
                                    ],
                                ),
                            ]
                        ),
                    ],
                    "cdr_token": OrderedDict(
                        [
                            ("uid", "EKI1"),
                            ("type", "RFID"),
                            ("contract_id", "CONTRACT2"),
                        ]
                    ),
                    "auth_method": "AUTH_REQUEST",
                    "authorization_reference": "FI*001*A*E2FA443602BD4E499C878B8BD6C",
                    "location_id": "EKI1",
                    "evse_uid": "1",
                    "connector_id": "1",
                    "currency": "PLN",
                    "total_cost": {"excl_vat": 22.8, "incl_vat": 28.27},
                    "status": "ACTIVE",
                    "last_updated": "2022-12-26T06:30:00Z",
                },
            ),
        )

        session_id = "FI*000*S*B58DDC4D3B304A47AD623C22147"

        session = Session.get_if_exists(uid=session_id)
        self.assertEqual(
            session.connector.tariff_ids.all().first().price(),
            "0,50€/kWh (Weekdays 7-21), 0,40€/kWh (Weekdays 21-7)",
            "Price formatting works differently than expected",
        )

        # The test data works with UTC, so let's move the chargers to London
        # session.location.time_zone = 'Europe/London'
        # session.location.save()

        def _meter_values_test(data, sess_id):
            timestamp: datetime
            for (
                kwh,
                soc,
                timestamp,
                expected_args,
                expected_response,
                expected_session_data,
            ) in data:
                # ic('*' * 60, kwh, soc, timestamp)
                try:
                    with self.subTest(kwh=kwh, timestamp=timestamp):
                        with (
                            time_machine.travel(timestamp, tick=False),
                            patch("ocpi22.util.is_our_identifier", return_value=True),
                        ):
                            from ocpi22.test_tariff_location_and_evse import meter_values
                            response = meter_values(
                                dict(
                                    session_id=sess_id,
                                    kwh=kwh,
                                    soc=soc,
                                    timestamp=timestamp.strftime(
                                        settings.OCPI_DATE_FORMAT
                                    ),
                                )
                            )

                        self.assertEqual(
                            response.status_code,
                            200,
                            f"Unexpected response from meter_values(): {response.data}",
                        )
                        if expected_args:
                            kwargs = simulation.tasks_requests.patch.call_args.kwargs
                            args = simulation.tasks_requests.patch.call_args.args
                            self.assertTrue(
                                compare_dicts_recursively(
                                    kwargs["data"], expected_args
                                ),
                                "send_update() got different parameters than expected",
                            )

                        if expected_response:
                            self.assertTrue(
                                compare_dicts_recursively(
                                    response.data, expected_response
                                ),
                                f"Response differs from expected: {response.data}",
                            )
                        if expected_session_data:
                            test_session = Session.get_if_exists(uid=session_id)
                            session_serializer = SessionSerializer(
                                test_session, context={"request": None}
                            )
                            self.assertTrue(
                                compare_dicts_recursively(
                                    session_serializer.data, expected_session_data
                                ),
                                "Session data differs from expected",
                            )
                except AssertionError:
                    ic(args[0], response.data)
                    raise

        find_route.cache_clear()
        _meter_values_test(meter_values_data, session_id)

        start_date_time = datetime(2022, 12, 1, 12, 0, tzinfo=pytz.utc)
        maxloop = 50
        performance_test_data = [
            (
                i,
                i * 100 / maxloop,
                start_date_time + timedelta(hours=i),
                None,
                None,
                None,
            )
            for i in range(0, maxloop)
        ]

        performance_session_id = "FI*000*S*PERFORMANCE*TEST"
        reset_queries()
        with Timer():
            _meter_values_test(performance_test_data, performance_session_id)

        long_queries = [i for i in connection.queries if float(i.get("time")) > 0.3]
        self.assertFalse(
            long_queries, f"There are SQL queries taking a long time: {long_queries}"
        )

        # self.assertLess(float(t), 4, f'Meter values performance test took {float(t):02f} seconds, which is too long')


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


def test_exception_handler(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (geopy.exc.GeocoderUnavailable, geopy.exc.GeocoderServiceError) as e:
            sys.stderr.write(f"Geocoder error during test: {e}")
            return None

    return wrapper


# @test_exception_handler
def put_location(data, url):
    request = api_factory.put(url)
    request.data = data
    request.user = AnonymousUser
    return LocationQuickViewSet().put(request)


# @test_exception_handler
def patch_location(data, url):
    request = api_factory.patch(url)
    request.data = data
    request.user = AnonymousUser
    return LocationQuickViewSet().patch(request)
