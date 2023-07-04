import json
from collections import OrderedDict

from django.conf import settings  # Do not remove if ic() is in use in this file


def compare_lists_recursively(expected, received, path='') -> bool:
    result = True
    for i, v in enumerate(expected):
        if i >= len(received):
            print(f'{expected[i]} not present in received')
            result = False
        if isinstance(v, (dict, OrderedDict)):
            if not compare_dicts_recursively(dict(v), dict(received[i]), path=f'{path}[{i}]'):
                # print(f'Dict {i} not equal in received')
                result = False
        elif isinstance(v, list):
            if not compare_lists_recursively(v, received[i], path=f'{path}[{i}]'):
                # print(f'List {i} not equal in received')
                result = False
        elif v not in received:
            print(f'{expected[i]} not equal in received')
            result = False
    return result


def compare_dicts_recursively(received, expected, path='', label='') -> bool:
    if not isinstance(received, (dict, OrderedDict)):
        received = json.loads(received)
        return compare_dicts_recursively(received, expected, path=path, label=label)
    if not isinstance(expected, (dict, OrderedDict)):
        expected = json.loads(expected)
        return compare_dicts_recursively(received, expected, path=path, label=label)
    result = True
    if not expected:
        print(f'Expected is empty (label={label})')
        return False
    for k, v in expected.items():
        if k not in received:
            print(f'Key {k} not present in received')
            result = False
        elif isinstance(v, (dict, OrderedDict)):
            if not compare_dicts_recursively(v, received[k], path=f'{path}.{k}'):
                # print(f'Dict {k} not equal in received')
                result = False
        elif isinstance(v, list):
            if not compare_lists_recursively(v, received[k], path=f'{path}.{k}'):
                # print(f'List {k} not equal in received')
                result = False
        elif v != k and v != received[k]:
            print('Not equal', k, v, received[k])
            result = False
    if not result:
        print(received, expected)
        print(f"The result doesn't match expected (label={label})")
    return result
