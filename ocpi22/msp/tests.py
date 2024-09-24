import doctest
import os
from unittest import TestCase
from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser, User

from rest_framework import status
from rest_framework.response import Response
from util import reverse
from rest_framework.test import APIRequestFactory

from ocpi22.msp.user import UserViewSet

api_factory = APIRequestFactory()


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite("ocpi22.msp.util"))
    tests.addTests(doctest.DocTestSuite("ocpi22.msp.map"))
    return tests


def send_request(data, function, url, user=AnonymousUser) -> Response:
    if "http" not in url:
        url = reverse(url)
    request = api_factory.post(url)
    request.data = data
    request.user = user
    return function(request)


class TestUserApi(TestCase):
    def test_user_lifecycle(self, get_json_mock: Mock):
        os.environ["TEST"] = "1"

        email = "eki@example.com"
        data = dict(
            email=email,
            firstname="Eki",
            lastname="Tapola",
            password="hello",
            confirm="hello",
            telephone="1234567890",
        )

        User.objects.filter(email=email).delete()

        response = send_request(data, UserViewSet().register, "user-register")
        # ic(response, response.data)
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, "Expected success"
        )
        # get_json_mock.assert_has_calls([call('artega-karo-range-plus'), call('artega-karo-range-plus')])

        #
        # Change password
        #

        user = User.objects.get(email=email)

        test_cases = (
            ("not-correct", "hello2", "hello2", status.HTTP_400_BAD_REQUEST),
            ("hello", "hello1", "hello2", status.HTTP_400_BAD_REQUEST),
            ("hello", "hello2", "hello2", status.HTTP_200_OK),
        )

        for current, password, confirm, expected_status in test_cases:
            args = (
                dict(current_password=current, password=password, confirm=confirm),
                UserViewSet().password,
                "user-password",
            )
            kwargs = dict(user=user)

            # ic(args, kwargs, expected_status)

            response = send_request(*args, **kwargs)
            self.assertEqual(
                response.status_code,
                expected_status,
                f"Expected password change to return {expected_status} "
                f"for test case {current}, {password}, {confirm}",
            )
