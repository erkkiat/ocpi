import json
from collections import OrderedDict

from django.conf import settings  # Do not remove if ic() is in use in this file


def compare_lists_recursively(received, expected, path='', label1='received', label2='expected') -> bool:
    assert isinstance(received, list) and isinstance(expected, list), \
        f'Not expecting {type(received)=} {type(expected)=}'
    result = True
    for i, v in enumerate(received):
        if i >= len(expected):
            print(f'{i=} {len(received)=} {len(expected)=} {type(received)=} {type(expected)=}')
            print(f'{received[3]=}')
            print(f'{received[4]=}')
            print(f'{received[5]=}')
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
            print(f'{path}.{key} not present in received'.strip('.'))
            result = False
        elif key not in expected:
            print(f'{path}.{key} not present in expected'.strip('.'))
            result = False
        elif isinstance(received_value, (dict, OrderedDict)) and isinstance(expected_value, (dict, OrderedDict)):
            result = result and compare_dicts_recursively(received_value, expected_value, path=f'{path}.{key}')
        elif isinstance(received_value, list) and isinstance(expected_value, list):
            result = result and compare_lists_recursively(received_value, expected_value, path=f'{path}.{key}')
        elif expected_value != received_value:
            print(f'{path}.{key} is not equal, should be "{expected_value}", but is "{received_value}" instead'.strip('.'))
            result = False
    # if label != 'expected':
    #     result = compare_dicts_recursively(expected, received, path=path, label='expected')
    if not result:
        ic(received, expected)
    return result
