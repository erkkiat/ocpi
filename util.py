import hashlib
import json
from dataclasses import is_dataclass, asdict
from typing import List, Any

import redis
from django.conf import settings

from django.urls import NoReverseMatch
from rest_framework.reverse import reverse as django_reverse

from ocpi22 import choices


class OCPIVersion:
    def __init__(self, version):
        """
        >>> OCPIVersion(OCPIVersion('2.1.1'))
        Traceback (most recent call last):
        ValueError: Invalid version number 211, options are ['22', '221']
        >>> OCPIVersion('2')
        Traceback (most recent call last):
        ValueError: Invalid version number 2, options are ['22', '221']
        >>> OCPIVersion('2.2.1')
        2.2.1
        >>> OCPIVersion('2.2.3')
        Traceback (most recent call last):
        ValueError: Invalid version number 223, options are ['22', '221']
        >>> OCPIVersion('221')  # doctest: +IGNORE_EXCEPTION_DETAIL
        2.2.1
        >>> OCPIVersion('223')  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ValueError: Invalid version number 223, options are ['22', '221']
        >>> OCPIVersion('2.2.1') == dict(this_is_not_going_to_work=True)
        Traceback (most recent call last):
          ...
        ValueError: Cannot compare OCPIVersion with <class 'dict'>
        >>> isinstance(hash(OCPIVersion('2.2.1')), int)
        True
        """
        version = self.remove_dots(version)
        if version in choices.VERSION_CHOICES_DICT:
            version = choices.VERSION_CHOICES_DICT[version]
        else:
            options = [str(x) for x in choices.VERSION_CHOICES_DICT.keys()]
            raise ValueError(f'Invalid version number {version}, options are {options}')
        self.version = str(version)
        self.pure_number = self.remove_dots(version)

    @staticmethod
    def remove_dots(s: str) -> str:
        return s.replace('.', '') if s else ''

    def __str__(self):
        return self.version

    def __repr__(self):
        return self.version

    def __eq__(self, other):
        """
        >>> OCPIVersion('221') == "2.2.1"
        True
        >>> OCPIVersion('221') == "221"
        True
        >>> OCPIVersion('22') == "221"
        False
        >>> OCPIVersion('22') == OCPIVersion('2.2')
        True
        >>> OCPIVersion('22') == OCPIVersion('2.2.1')
        False
        """
        if isinstance(other, str):
            return self.pure_number == self.remove_dots(other)
        elif isinstance(other, OCPIVersion):
            return self.pure_number == other.pure_number
        else:
            raise ValueError(f'Cannot compare OCPIVersion with {type(other)}')

    def __hash__(self):
        return hash(self.pure_number)


def reverse(s, args=[], request=None, version=None, kwargs=None) -> str:
    """
    >>> reverse('location-by-id', args=['2.2.1', 1, 2, 3])
    '/ocpi/2.2.1/locations/1/2/3'

    @param s:
    @param args:
    @param request:
    @param version:
    @param kwargs:
    @return:
    """
    version = OCPIVersion(version or request.version or '2.2.1' if request else '2.2.1')
    version_args = None
    # Handle versioning wether args or kwargs is used (can't use both with reverse())
    if kwargs:
        kwargs['version'] = version
    else:
        version_args = [version, *args]
    try:
        return django_reverse(s, args=version_args, request=request, kwargs=kwargs)
    except NoReverseMatch:
        return django_reverse(s, args=args, request=request)


def url_link(href, text, target='') -> str:
    """
    >>> url_link('https://www.google.com', 'Google')
    '<a href="https://www.google.com">Google</a>'
    """
    target = f' target="{target}" ' if target else ''
    return f'<a{target} href="{href}">{text}</a>'


def format_url(url, **kwargs) -> str:
    """
    >>> format_url("https://fakehost/start/{evse_id}/", evse_id=1)
    'https://fakehost/start/1/'
    >>> format_url(b"https://fakehost/start/", evse_id=1, connector_id=2)
    'https://fakehost/start/'
    """
    try:
        if isinstance(url, bytes):
            url = url.decode("utf-8")
        return url.format(**kwargs)
    except KeyError as e:
        from ocpi22 import logging
        logging.error(f'Unknown URL variable in format_url: {e}')
        return url


def numbers_are_consequtive(numbers: List[int]) -> bool:
    """
    >>> numbers_are_consequtive([1, 2, 3, 4, 5])
    True
    >>> numbers_are_consequtive([2, 3, 4, 5])
    False
    >>> numbers_are_consequtive([1, 2, 3, 5])
    False
    >>> numbers_are_consequtive([1, 2, 3, 5, 6])
    False
    >>> numbers_are_consequtive([1, 2, 3, 4, 5, 6, 7, 8, 9])
    True
    """
    if not numbers or min(numbers) != 1:
        return False
    return numbers == list(range(min(numbers), max(numbers) + 1))


def member_hash(obj: Any) -> int:
    """
    >>> from dataclasses import dataclass
    >>> @dataclass
    ... class Test:
    ...     a: int
    ...     b: str
    >>> member_hash(Test(1, 'a'))
    947394849765499942087305821015908087369400221253735434007988480287487229907
    """
    attr_dict = vars(obj)
    attr_dict = attr_dict.copy()
    attr_dict.pop('_state', None)
    # Convert the dictionary to a string and hash it
    attr_str = json.dumps(attr_dict, sort_keys=True, default=str)
    thehash = int(hashlib.sha256(attr_str.encode()).hexdigest(), 16)
    return thehash


class RedisStore:
    def __init__(self, namespace=None, expiration=None):
        self.namespace = namespace
        self.expiration = expiration

    def _format_key(self, key, namespace=None):
        """
        >>> test = RedisStore()
        >>> test._format_key('test')
        'test'
        >>> test._format_key('a', namespace='b')
        'b-a'
        """
        namespace = namespace or self.namespace
        if not namespace:
            return key
        return f'{namespace}-{key}'

    def __setitem__(self, key, value):
        namespace_key = self._format_key(key)
        # ic()
        # ic(key, namespace_key, value, self.expiration)
        if isinstance(value, dict):
            value = json.dumps(value, default=str)  # serializes also dates
        elif is_dataclass(value):
            value = json.dumps(asdict(value), default=str)
        redis_store.set(namespace_key, value, self.expiration)

    def __getitem__(self, item):
        # ic()
        # ic(item)
        namespace_key = self._format_key(item)
        value = redis_store.get(namespace_key)
        if not value:
            raise KeyError(f'No {item} stored for {self.namespace}')
        if "{" in value:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        # ic(item, namespace_key, value)
        return value


redis_store = redis.from_url(settings.REDIS_URL, decode_responses=True)
default_error_messages = dict(
    object_missing='There is no {name} with UID `{uid}` in our database',
    no_connector_in_evse='There is no connector with UID `{uid}` in EVSE `{evse}`.',
    location_evse_missing='There is no EVSE with UID `{evse}` in location `{location}`.',
)


class HashableDict(dict):
    """
    >>> d = HashableDict(a=1, b=2)
    >>> d
    {'a': 1, 'b': 2}
    >>> d['a']
    1
    >>> d['c'] = 3
    Traceback (most recent call last):
      ...
    RuntimeError: HashableDict is immutable
    >>> d.update(a=2)
    Traceback (most recent call last):
      ...
    RuntimeError: HashableDict is immutable
    >>> d.clear()
    Traceback (most recent call last):
      ...
    RuntimeError: HashableDict is immutable
    >>> del d['a']
    Traceback (most recent call last):
        ...
    RuntimeError: HashableDict is immutable
    """

    def __hash__(self):
        return hash(tuple(sorted(super().items())))

    def __setitem__(self, key, value):
        raise RuntimeError('HashableDict is immutable')

    def __delitem__(self, key):
        raise RuntimeError('HashableDict is immutable')

    def update(self, **new_kwargs):
        raise RuntimeError('HashableDict is immutable')

    def clear(self):
        raise RuntimeError('HashableDict is immutable')


def with_trailing_slash(url):
    """
    >>> with_trailing_slash('https://fakehost/start')
    'https://fakehost/start/'
    >>> with_trailing_slash('https://fakehost/start/')
    'https://fakehost/start/'
    """
    if url.endswith('/'):
        return url
    return f'{url}/'
