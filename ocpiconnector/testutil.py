import json
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from functools import wraps
from types import FunctionType
from typing import Union, Iterable, Mapping, Any
from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser

from requests import Response
from rest_framework.test import APIRequestFactory

from django.test import Client, TestCase

from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.headers import make_headers
from ocpi22.test_data import expected_get_responses, expected_get_headers
from ocpiconnector.party import Party
from ocpi22.ocpi.partners import partners_cache
from ocpi22.routing import find_route
from ocpi22.tokens.auth import _authorize_token, _get_authorization_from_sessions
from util import unwrap

client = Client()


def compare_lists_recursively(
    received, expected, path="", label1="received", label2="expected", swapped=False
) -> bool:
    # received = sorted(received, key=lambda x: hash(make_hashable(x))) if isinstance(received, list) else received
    # expected = sorted(expected, key=lambda x: hash(make_hashable(x))) if isinstance(expected, list) else expected

    assert isinstance(received, (list, tuple)) and isinstance(
        expected, (list, tuple)
    ), f"Not expecting {type(received)=} {type(expected)=} {received=} {expected=}"
    result = True
    output = ""
    for i, v in enumerate(received):
        if i >= len(expected):
            output = f"{path}.{received[i]} not present in {label2}".strip(".")
            result = False
        elif isinstance(v, (dict, OrderedDict)):
            if not compare_dicts_recursively(
                dict(v), dict(expected[i]), path=f"{path}.{i}"
            ):
                result = False
        elif isinstance(v, (list, tuple)):
            if not compare_lists_recursively(v, expected[i], path=f"{path}.{i}"):
                result = False
        elif v not in received:
            output = f"{path}.{received[i]} not equal in {label2}".strip(".")
            result = False
        elif v != expected[i] and (expected[i] != "***" and v != "***"):
            output = f'{path}.{received[i]} is not equal, should be "{expected[i]}", but is "{v}" instead'.strip(
                "."
            )
            result = False
    if not swapped:
        result = result and compare_lists_recursively(
            expected, received, path=path, label1=label2, label2=label1, swapped=True
        )
    if not result:
        print(output)
    return result


def compare_dicts_recursively(received, expected, path="", label="") -> bool:
    """
    Compare the content and structure of two dicts recursively. "***" matches anything.
    When a list is encountered, it is compared using compare_lists_recursively.
    """
    output = ""
    if isinstance(received, (str, bytes, bytearray)):
        return compare_dicts_recursively(
            json.loads(received), expected, path=path, label=label
        )
    if isinstance(expected, (str, bytes, bytearray)):
        return compare_dicts_recursively(
            received, json.loads(expected), path=path, label=label
        )
    result = True
    assert isinstance(expected, dict) and isinstance(
        received, dict
    ), f"Not expecting {type(received)=} {type(expected)=}"
    keys = list(expected.keys())
    keys += list(received.keys())
    for key in set(keys):
        received_value = received[key] if key in received else None
        expected_value = expected[key] if key in expected else None
        if key not in received:
            output = f"{path}.{key} not present in received".strip(".")
            result = False
        elif key not in expected:
            output = f"{path}.{key} not present in expected".strip(".")
            result = False
        elif isinstance(received_value, (dict, OrderedDict)) and isinstance(
            expected_value, (dict, OrderedDict)
        ):
            result = result and compare_dicts_recursively(
                received_value, expected_value, path=f"{path}.{key}"
            )
        elif isinstance(received_value, list) and isinstance(expected_value, list):
            result = result and compare_lists_recursively(
                received_value, expected_value, path=f"{path}.{key}"
            )
        elif (
            expected_value != received_value
            and (expected_value != "***" and received_value != "***")
            and str(expected_value) != str(received_value)
        ):
            output = f'{path}.{key} is not equal, should be "{expected_value}", but is "{received_value}" instead'.strip(
                "."
            )
            result = False
    # if label != 'expected':
    #     result = compare_dicts_recursively(expected, received, path=path, label='expected')
    if not result:
        print(output)
    return result


class OCPIAPIRequestFactory(APIRequestFactory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def request(
        self, sender: Party | CredentialsRole = None, to: Party = None, **kwargs
    ):
        if isinstance(sender, CredentialsRole):
            ocpi_party = sender
        else:
            ocpi_party = (
                get_credentialsrole(None, sender, create=True) if sender else None
            )
        credentials = (
            ocpi_party.credentials if ocpi_party else Credentials.objects.first()
        )
        assert credentials
        headers = make_headers(
            credentials.ours_base64(),
            to=to or Party("FI", "CPO"),
            sender=ocpi_party.get_party() if ocpi_party else Party("FI", "HUB"),
        )
        headers.update(kwargs)
        request = super().request(**headers)
        request.credentials = credentials
        request.ocpi_party = ocpi_party
        request.version = "2.2.1"
        request.user = AnonymousUser()
        versioning_mock = Mock()
        versioning_mock.reverse.return_value = "http://dummy.url/"
        request.versioning_scheme = versioning_mock
        request.versioning_namespace = None
        request.versioning_query_param = "version"
        request.headers = request.META
        return request


def mocked_object_get(url, *_args, **kwargs):
    try:
        credentials = Credentials.objects.get(pk=2)
        headers = kwargs["headers"]
        # Let's swap the other token and receive this request as if it comes from outside
        headers["HTTP_AUTHORIZATION"] = f"Token {credentials.ours_base64()}"

        with patch(
            "ocpi22.ocpi.auth.OCPIPermission.has_permission"
        ) as mock_has_permission:
            # We will test authentication separately, so let's just make this test simpler and more focused
            mock_has_permission.return_value = True
            result = client.get(url, **headers)

        json_text = result.content.decode("utf-8")
        assert (
            "DOCTYPE" not in json_text
        ), f"URL {url} is returning HTML, when excepting JSON"

        content = json.loads(json_text)
        assert compare_dicts_recursively(
            content, expected_get_responses[url]
        ), f"Expecting a different result for {url}: {content}"

        response_headers = dict(result.headers)
        response_headers.pop("Content-Length", None)
        expected_headers = expected_get_headers[url]
        expected_headers.pop("Content-Length", None)
        assert compare_dicts_recursively(
            response_headers, expected_headers
        ), f"Expecting different headers for {url}: {response_headers}"

        return result
    except (AssertionError, KeyError):
        raise


@dataclass
class Simulation:
    tasks_requests: Mock
    get_platform_revision: Mock
    redis_store: Mock
    webhook_requests: Mock
    uuid4: Mock
    ocpi_requests: Mock
    logging: Mock
    get_our_credentialsrole: Mock

    original_redis_store: FunctionType
    original_get_our_credentialsrole: FunctionType

    def reset(self):
        for x in self.__dict__.values():
            if isinstance(x, Mock):
                x.reset_mock()

    def __post_init__(self):
        self.tasks_requests.post.side_effect = self.post
        self.tasks_requests.get.side_effect = self.get
        self.tasks_requests.patch.side_effect = (
            self.put
        )  # NOTE patch is re-used for PUT
        self.tasks_requests.put.side_effect = self.put
        self.tasks_requests.delete.side_effect = self.delete

        self.ocpi_requests.get.side_effect = mocked_object_get

        self.get_platform_revision.return_value = "REVISION"

        self.redis_store.get.side_effect = lambda x: {
            "callback-start_transaction_url": "http://john:his-password@fakehost/start/{evse_id}/",
            "callback-stop_transaction_url": "http://john:his-password@fakehost/stop/{evse_id}/",
            "callback-session_url": "http://localhost/session/{uid}/",
            "callback-invoicing_url": "http://localhost/invoice/{uid}/",
            "callback-reserve_now_url": "http://localhost/reserve/{evse_id}/",
            "callback-chargepoint_status_url": "http://localhost/status/{evse_id}/",
        }.get(
            x, self.original_redis_store.get(x)
        )  # Revert back to the actual Redis.get() for any other keys

        self.webhook_requests.put.return_value = FakeResponse(
            200, {"timeout": 90, "result": "ACCEPTED"}
        )

        self.uuid4.return_value = MockUuid4()

        self.enable_logging_exceptions()

        # Unit tests are loading their own fixtures, so we need to clear the cache not to get the fixture data mixed up
        find_route.cache_clear()
        _authorize_token.cache_clear()
        _get_authorization_from_sessions.cache_clear()
        partners_cache.clear()

        self.get_our_credentialsrole.side_effect = (
            lambda x: self.original_get_our_credentialsrole(x)
        )

    @contextmanager
    def our_msp_role(self, party):
        """Set our MSP role for the duration of the context, create role if it does not exist"""
        role = get_credentialsrole(None, party, create=True)
        self.get_our_credentialsrole.side_effect = None
        self.get_our_credentialsrole.return_value = role
        yield role
        self.get_our_credentialsrole.side_effect = (
            lambda x: self.original_get_our_credentialsrole(x)
        )

    @contextmanager
    def no_logging_exceptions(self):
        self.disable_logging_exceptions()
        yield
        self.enable_logging_exceptions()

    @contextmanager
    def assert_error_logged(self, text: Union[str, Iterable[str]]):
        """
        Expect one or more logging.error() calls and make sure
        specified texts are included in the corresponding arguments
        """

        def assert_logged_error_has_text(*args, **kwargs):
            """This wrapper should normally receive a single args[0] each time logging.error() is called"""
            success = False
            if isinstance(text, Iterable):
                # Loop through all the texts and corresponding arguments
                success = any([t in args[0] for t in text])
            elif isinstance(text, str):
                success = text in args[0]
            if not success:
                self.enable_logging_exceptions()  # Avoid loops
                raise AssertionError(
                    f'Expected "{text}" to be logged as error, but it was "{args[0]}" instead'
                )

        self.enable_logging_exceptions(assert_logged_error_has_text)
        yield
        self.enable_logging_exceptions()

    def disable_logging_exceptions(self):
        """Switch off logging error exceptions for the simulation"""
        self.logging.error.side_effect = None

    def enable_logging_exceptions(self, func=None):
        """
        (Re-)activate logging error exceptions
        By default any error logged during a simulation test will raise an exception,
        so that they are not ignored unintentionally
        """

        def exception_handler_for_logged_errors(*args, **kwargs):
            raise RuntimeError(f"Test logged an error: {args=}, {kwargs=}")

        self.logging.error.side_effect = func or exception_handler_for_logged_errors

    def post(self, *args, **kwargs):
        return self._request("POST", *args, **kwargs)

    def get(self, *args, **kwargs):
        return self._request("GET", *args, **kwargs)

    def put(self, *args, **kwargs):
        """Used for both PUT and PATCH"""
        return self._request("PUT", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._request("DELETE", *args, **kwargs)

    @staticmethod
    def _request(method, url, json=None, response=None, **kwargs):
        return FakeResponse(200, response or {})


def simulate_surrounding_world(func):
    """
    Patch all external dependencies to make sure the test is isolated from the outside world
    - All Mocks are accesible through the simulation object as simulation.<mock_name>
    - You can switch mocks on and off, and set side_effects
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Store the original redis_store for use during the test for access to actual Redis
        from util import redis_store

        original_redis_store = redis_store
        from ocpi22.ocpi.api import get_our_credentialsrole

        original_get_our_credentialsrole = unwrap(get_our_credentialsrole)

        with (
            patch("ocpi22.tasks.requests.session") as tasks_requests,
            patch("ocpi22.ocpi.headers.get_platform_revision") as get_platform_revision,
            patch(
                "ocpi22.util.redis_store",
            ) as redis_store,
            patch("ocpi22.legacy_webhooks.requests") as webhook_requests,
            patch("ocpi22.ocpi.util.uuid.uuid4", return_value=MockUuid4()) as uuid4,
            patch("ocpi22.ocpi.util.requests") as ocpi_requests,
            patch("ocpi22.ocpi_logging.error") as logging_error,
            patch("ocpi22.ocpi_logging.info") as logging_info,
            patch("ocpi22.ocpi_logging.warning") as logging_warning,
            patch("ocpi22.ocpi.api.get_our_credentialsrole") as get_our_credentialsrole,
        ):
            simulation = Simulation(
                tasks_requests=tasks_requests,
                get_platform_revision=get_platform_revision,
                redis_store=redis_store,
                webhook_requests=webhook_requests,
                uuid4=uuid4,
                ocpi_requests=ocpi_requests,
                logging=Mock(
                    error=logging_error, warning=logging_warning, info=logging_info
                ),
                original_redis_store=original_redis_store,
                get_our_credentialsrole=get_our_credentialsrole,
                original_get_our_credentialsrole=original_get_our_credentialsrole,
            )
            kwargs["simulation"] = simulation
            return func(*args, **kwargs)

    return wrapper


@dataclass(eq=True, frozen=True)
class FakeResponse:
    status_code: int = field(default=200)
    data: dict = field(default_factory=dict)
    reason: str = field(default="Mocked response")
    headers: dict = field(default_factory=dict)
    elapsed: timedelta = field(default_factory=lambda: timedelta(seconds=0.1))

    def json(self):
        return self.data

    @property
    def text(self):
        return self.data


class MockUuid4:
    number: int

    def __init__(self, number=1):
        self.number = number

    @property
    def hex(self):
        return f"MOCK-{self.number}"


class MockResponse:
    def __init__(
        self, json_data, status_code, headers=None, data=None, reason="Mocked function"
    ):
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


def make_json_response(data, status_code=200) -> Response:
    response = Response()
    response.status_code = status_code
    response.encoding = "UTF-8"
    response.json = lambda: data
    data_str = json.dumps(data).encode("UTF-8")
    response._content = data_str
    return response


@dataclass
class FakeUser:
    username: str
    is_staff: bool
    is_superuser: bool
    is_authenticated: bool = True


def get_fake_admin():
    return FakeUser("admin", True, True)


class BetterTestCase(
    TestCase
):  # Seeing first how this works before during a big refactoring
    def assertDictEqual(
        self, d1: Mapping[Any, object], d2: Mapping[Any, object], msg: Any = ...
    ) -> None:
        self.assertTrue(compare_dicts_recursively(d1, d2), msg)

    def assertListEqual(
        self, list1: list[Any], list2: list[Any], msg: Any = ...
    ) -> None:
        self.assertTrue(compare_lists_recursively(list1, list2), msg)
