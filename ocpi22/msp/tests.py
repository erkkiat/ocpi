import doctest

from django.contrib.auth.models import AnonymousUser

from rest_framework.response import Response
from util import reverse
from rest_framework.test import APIRequestFactory

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
