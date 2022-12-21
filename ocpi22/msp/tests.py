import doctest
import os
from unittest import TestCase
from unittest.mock import patch, Mock

from django.contrib.auth.models import AnonymousUser, User

from rest_framework import status
from rest_framework.response import Response
from util import reverse
from rest_framework.test import APIRequestFactory

from cars import test_data
from ocpi22.msp.user import UserViewSet

api_factory = APIRequestFactory()


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.msp.util'))
    return tests


def send_request(data, function, url, user=AnonymousUser) -> Response:
    if 'http' not in url:
        url = reverse(url)
    request = api_factory.post(url)
    request.data = data
    request.user = user
    return function(request)


@patch('cars.cars.get_json', return_value=test_data.cars_json)  # This is not working
class TestUserApi(TestCase):
    def test_user_lifecycle(self, get_json_mock: Mock):
        os.environ['TEST'] = "1"

        email = 'eki@example.com'
        data = dict(
            email=email,
            firstname='Eki',
            lastname='Tapola',
            password='hello',
            confirm='hello',
            telephone='1234567890',
            vehicle='artega-karo-range-plus',
        )

        User.objects.filter(email=email).delete()
        user_count_before = User.objects.all().count()

        #
        # Try with an unknown vehicle
        #

        bad_car = 'non-existent-car'
        bad_data = data.copy()
        bad_data.update(vehicle=bad_car)

        response = send_request(bad_data, UserViewSet().register, 'user-register')
        # ic(response, response.data)
        # ic(get_json_mock.call_count)
        # get_json_mock.assert_called_once()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, 'Expecting car model validation to fail')

        user_count_after = User.objects.all().count()
        self.assertEqual(user_count_before, user_count_after,
                         'User registration should fail with a non-existent vehicle')
        #
        # All should be good
        #

        response = send_request(data, UserViewSet().register, 'user-register')
        # ic(response, response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, 'Expected success')
        # get_json_mock.assert_has_calls([call('artega-karo-range-plus'), call('artega-karo-range-plus')])

        #
        # Change password
        #

        user = User.objects.get(email=email)

        test_cases = (
            ('not-correct', 'hello2', 'hello2', status.HTTP_400_BAD_REQUEST),
            ('hello', 'hello1', 'hello2', status.HTTP_400_BAD_REQUEST),
            ('hello', 'hello2', 'hello2', status.HTTP_200_OK),
        )

        for current, password, confirm, expected_status in test_cases:
            args = (
                dict(
                    current_password=current,
                    password=password,
                    confirm=confirm
                ),
                UserViewSet().password,
                'user-password')
            kwargs = dict(user=user)

            # ic(args, kwargs, expected_status)

            response = send_request(*args, **kwargs)
            self.assertEqual(response.status_code, expected_status,
                             f'Expected password change to return {expected_status} '
                             f'for test case {current}, {password}, {confirm}')
