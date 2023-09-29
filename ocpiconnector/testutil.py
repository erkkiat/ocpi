import json
from collections import OrderedDict

from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from django.conf import settings  # Do not remove if ic() is in use in this file

from ocpi22.models.credentials import Credentials
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.headers import make_headers
from ocpiconnector.ocpi_identities import Party


def compare_lists_recursively(received, expected, path='', label1='received', label2='expected') -> bool:
    assert isinstance(received, (list, tuple)) and isinstance(expected, (list, tuple)), \
        f'Not expecting {type(received)=} {type(expected)=}'
    result = True
    for i, v in enumerate(received):
        if i >= len(expected):
            print(f'{i=} {len(received)=} {len(expected)=} {type(received)=} {type(expected)=}')
            # print(f'{received[3]=}')
            # print(f'{received[4]=}')
            # print(f'{received[5]=}')
            print(f'{path}.{received[i]} not present in {label2}'.strip('.'))
            result = False
        elif isinstance(v, (dict, OrderedDict)):
            if not compare_dicts_recursively(dict(v), dict(expected[i]), path=f'{path}.{i}'):
                result = False
        elif isinstance(v, list):
            if not compare_lists_recursively(v, expected[i], path=f'{path}.{i}'):
                result = False
        elif v not in received:
            print(f'{path}.{received[i]} not equal in {label2}'.strip('.'))
            result = False
    if label1 != 'expected':
        result = compare_lists_recursively(expected, received, path=path, label1='expected', label2='received')
    return result


def compare_dicts_recursively(received, expected, path='', label='') -> bool:
    # ic(path, label, received, expected)
    output = ''
    if not isinstance(received, (dict, OrderedDict)):
        return compare_dicts_recursively(json.loads(received), expected, path=path, label=label)
    if not isinstance(expected, (dict, OrderedDict)):
        return compare_dicts_recursively(received, json.loads(expected), path=path, label=label)
    result = True
    keys = list(expected.keys())
    keys += list(received.keys())
    for key in set(keys):
        received_value = received[key] if key in received else None
        expected_value = expected[key] if key in expected else None
        if key not in received:
            output = f'{path}.{key} not present in received'.strip('.')
            result = False
        elif key not in expected:
            output = f'{path}.{key} not present in expected'.strip('.')
            result = False
        elif isinstance(received_value, (dict, OrderedDict)) and isinstance(expected_value, (dict, OrderedDict)):
            result = result and compare_dicts_recursively(received_value, expected_value, path=f'{path}.{key}')
        elif isinstance(received_value, list) and isinstance(expected_value, list):
            result = result and compare_lists_recursively(received_value, expected_value, path=f'{path}.{key}')
        elif expected_value != received_value:
            output = f'{path}.{key} is not equal, should be "{expected_value}", but is "{received_value}" instead'.strip('.')
            result = False
    # if label != 'expected':
    #     result = compare_dicts_recursively(expected, received, path=path, label='expected')
    if not result:
        ic(received, expected)
        print(output)
    return result


class OCPIAPIRequestFactory(APIRequestFactory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def request(self, sender: Party = None, **kwargs):
        ocpi_party = get_credentialsrole(None, sender, create=True) \
            if sender else None
        credentials = ocpi_party.credentials if ocpi_party else Credentials.objects.first()
        headers = make_headers(
            credentials.ours_base64(), to=Party('FI', 'CPO'), sender=sender
        )
        headers.update(kwargs)
        request = super().request(**headers)
        request.credentials = credentials
        request.ocpi_party = ocpi_party
        request.version = '2.2.1'
        request.user = AnonymousUser()
        request.versioning_scheme = 'query_parameter'
        request.versioning_namespace = None
        request.versioning_query_param = 'version'
        request.headers = request.META
        return request


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
        assert compare_dicts_recursively(response_headers, expected_headers), \
            f"Expecting different headers for {url}: {response_headers}"

        return result
    except (AssertionError, KeyError):
        # ic(url, recursive_sort_dict(response_headers), recursive_sort_dict(expected_headers))
        # ic(recursive_sort_dict(content), recursive_sort_dict(expected_get_responses[url]))
        raise
