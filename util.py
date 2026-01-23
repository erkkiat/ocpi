import hashlib
import json
import pickle
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import time, datetime as python_datetime, date
from functools import wraps
from logging import getLogger
from typing import List, Any, Optional, Union
from urllib.parse import urljoin

import pytz
import redis
from django.conf import settings

from django.urls import NoReverseMatch
from django.utils.datetime_safe import datetime
from rest_framework.response import Response
from rest_framework.reverse import reverse as django_reverse

from ocpi22 import choices

logger = getLogger(__name__)

default_error_messages = dict(
    object_missing="There is no {name} with UID `{uid}` in our database",
    no_connector_in_evse="There is no connector with UID `{uid}` in EVSE `{evse}`.",
    location_evse_missing="There is no EVSE with UID `{evse}` in location `{location}`.",
    evse_owner_missing="There is no EVSE with UID `{evse}` owned by `{ocpi_master}`.",
)


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
            raise ValueError(f"Invalid version number {version}, options are {options}")
        self.version = str(version)
        self.pure_number = self.remove_dots(version)

    @staticmethod
    def remove_dots(s: str) -> str:
        return s.replace(".", "") if s else ""

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
            raise ValueError(f"Cannot compare OCPIVersion with {type(other)}")

    def __hash__(self):
        return hash(self.pure_number)


def reverse(s, args=None, request=None, version=None, kwargs=None) -> str:
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
    args = args or []
    version = OCPIVersion(version or request.version or "2.2.1" if request else "2.2.1")
    version_args = None
    # Handle versioning wether args or kwargs is used (can't use both with reverse())
    if kwargs:
        kwargs["version"] = version
    else:
        version_args = [str(version), *args]
    try:
        return django_reverse(s, args=version_args, request=request, kwargs=kwargs)
    except NoReverseMatch:
        return django_reverse(s, args=args, request=request)


def url_link(href, text, target="") -> str:
    """
    >>> url_link('https://www.google.com', 'Google')
    '<a href="https://www.google.com">Google</a>'
    """
    target = f' target="{target}" ' if target else ""
    return f'<a{target} href="{href}">{text}</a>'


def format_url(url, **kwargs) -> str:
    """
    >>> format_url("https://fakehost/start/{evse_id}/", evse_id=1)
    'https://fakehost/start/1/'
    >>> format_url("https://fakehost/start/", evse_id=1, connector_id=2)
    'https://fakehost/start/'
    """
    try:
        if isinstance(url, bytes):
            url = url.decode("utf-8")
        return url.format(**kwargs)
    except KeyError as e:
        logger.exception(f"Unknown URL variable in format_url: {e}")
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
    attr_dict.pop("_state", None)
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
        'b:a'
        """
        namespace = namespace or self.namespace
        if not namespace:
            return key
        return f"{namespace}:{key}"

    def store(self, key, value, expiration=None):
        """
        Store a value in Redis, with expiration specified at initialization.
        The key is preformatted with the namespace. This is to make inheritance easier.
        """
        if isinstance(expiration, (datetime, python_datetime)):
            expiration = expiration - datetime.now(pytz.utc)
        value = pickle.dumps(value)
        redis_store.set(self._format_key(key), value, expiration or self.expiration)

    def __setitem__(self, key, value):
        self.store(key, value)

    def retrieve(self, key) -> Optional[Any]:
        value = ""
        try:
            key = self._format_key(key)
            value = redis_store.get(key)
            if not value:
                raise KeyError(f"Key {key} not found in Redis")
            if isinstance(value, str) and value.startswith("{"):
                # print(f'Parsing {value} as JSON')
                value = json.loads(value)
            else:
                # print(f'Parsing {value} using pickle')
                value = pickle.loads(value)
            return value
        except pickle.UnpicklingError:
            logger.exception(
                f"Error retrieving and decoding Redis key {key} as pickled"
            )
            # print(f'Error retrieving Redis key {key} as pickled: {e}')
        except (TypeError, UnicodeDecodeError):
            logger.exception(f"Error decoding value {value} from Redis with key {key}")
            # print(f'Error decoding value from Redis with key {key}: {e}')
        except json.JSONDecodeError:
            logger.exception(f"Error decoding Redis key {key} value {value} as JSON")
            # print(f'Error decoding Redis key {key} value {value} as JSON: {e}')
        # If reading the stored data fails, there is not much we can do, but for caching this is ok
        raise KeyError(f"Key {key} not found in Redis")

    def __getitem__(self, key):
        return self.retrieve(key)


redis_store = redis.from_url(settings.REDIS_URL, decode_responses=False)


class DistributedCache(RedisStore):
    def __init__(self, *args, exclude=None, namespace=None, **kwargs):
        self.exclude = exclude
        namespace = namespace or settings.HOSTNAME_SHORT
        super().__init__(*args, namespace=namespace, **kwargs)

    @dataclass
    class CacheInfo:
        hits: int
        misses: int
        maxsize: int  # Not supported due to performance issues
        currsize: int  # Not supported due to performance issues

        def __repr__(self):
            return f"CacheInfo(hits={self.hits}, misses={self.misses}, maxsize={self.maxsize}, currsize={self.currsize})"

    def generate_cache_key(self, func, args, kwargs):
        key = f"{func.__module__}.{func.__name__}:{args}:{kwargs}"
        return f"{self.namespace}:{hashlib.md5(pickle.dumps(key)).hexdigest()}"

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = self.generate_cache_key(func, args, kwargs)
            try:
                cached_value = self.retrieve(key)
                self.hits += 1
                return cached_value
            except KeyError:
                self.misses += 1
                value = func(*args, **kwargs)
                if self.exclude and self.exclude(value):
                    return value
                self.store(key, value)
                return value

        def clear_cache_item(*args, **kwargs):
            key = self.generate_cache_key(func, args, kwargs)
            redis_store.delete(f"{self.namespace}:{key}")

        def cache_clear():
            for key in redis_store.scan_iter(f"{self.namespace}:*"):
                if not redis_store.delete(key):
                    logger.warning(f"Could not delete key {key} from Redis")
            self.hits = 0
            self.misses = 0

        def cache_info():
            return self.CacheInfo(self.hits, self.misses, 0, 0)

        self.hits = 0
        self.misses = 0
        self.namespace = self.namespace or f"{func.__module__}.{func.__name__}"

        wrapper.clear_cache_item = clear_cache_item  # Attach the methods to the wrapper
        wrapper.cache_clear = cache_clear
        wrapper.cache_info = cache_info

        return wrapper


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
        return hash(tuple(sorted(make_hashable(super().items()))))

    def __setitem__(self, key, value):
        raise RuntimeError("HashableDict is immutable")

    def __delitem__(self, key):
        raise RuntimeError("HashableDict is immutable")

    def update(self, **new_kwargs):
        raise RuntimeError("HashableDict is immutable")

    def clear(self):
        raise RuntimeError("HashableDict is immutable")


def with_trailing_slash(url):
    """
    >>> with_trailing_slash('https://fakehost/start')
    'https://fakehost/start/'
    >>> with_trailing_slash('https://fakehost/start/')
    'https://fakehost/start/'
    """
    if url.endswith("/"):
        return url
    return f"{url}/"


def convert_to_time(t) -> time:
    if isinstance(t, str):
        return time(*t.split(":"))
    if isinstance(t, (datetime, python_datetime)):
        return t.time()
    return t


def time_lte(
    time1: Union[time, str, datetime], time2: Union[time, str, datetime]
) -> bool:
    time1 = convert_to_time(time1)
    time2 = convert_to_time(time2)
    return time1 <= time2


def time_lt(
    time1: Union[time, str, datetime], time2: Union[time, str, datetime]
) -> bool:
    time1 = convert_to_time(time1)
    time2 = convert_to_time(time2)
    return time1 < time2


def title_case(name: str) -> str:
    """Convert a name to title case"""
    return name.replace("-", " ").replace("_", " ").title()


def replace_links(result):
    """Replace all links in the result with the corresponding URL using reverse()
    >>> replace_links('Check [msp-authorize-webhook] for details.')
    'Check <a href="/api/msp/v1/webhook/authorize/">Msp Authorize Webhook</a> for details.'
    """

    def replacer(match):
        view_name = match.group(1)  # Extract the view name from the matched string.
        return f'<a href="{reverse(view_name)}">{title_case(view_name)}</a>'  # Reverse the URL for that view.

    pattern = r"\[([\w-]+)\]"  # Regular expression to match "[something]"
    return re.sub(pattern, replacer, result)


def unwrap(func):
    """
    Recursively unwrap a decorated function to provide direct access to the original function.
    @param func: A function decorated with one or more decorators
    @return: Unwrapped (undecorated) function
    """
    if hasattr(func, "__wrapped__"):
        return unwrap(func.__wrapped__)
    return func


class ErrorLoggingResponse(Response):
    def __init__(
        self,
        data=None,
        status=200,
        template_name=None,
        headers=None,
        exception=False,
        content_type=None,
    ):
        if status >= 400:
            logger.error(f"Error {status}: {data}")
        super().__init__(data, status, template_name, headers, exception, content_type)


def get_message_by_language(messages: list, language: str) -> str:
    """
    >>> from ocpi22.choices import MessageTexts
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), 'en')
    'Stopping charging session'
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), 'FI')
    'Latausistuntoa lopetellaan'
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), 'CH')
    'Stopping charging session'
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), '')
    'Stopping charging session'
    """
    if not messages:
        return ""
    language = language.upper()
    for message in messages:
        if message.get("language") == language:
            return message.get("text")
    return (
        get_message_by_language(messages, "EN")
        if language != "EN"
        else messages[0].get("text")
    )


def convert_to_utc_midnight(d: Union[date, datetime]) -> datetime:
    """
    Convert the date to a datetime at midnight of that day in UTC

    >>> str(convert_to_utc_midnight(datetime(2023, 1, 1)))
    '2023-01-01 00:00:00+00:00'

    @param d: A date
    @return: A datetime object at midnight in UTC
    """
    return datetime(d.year, d.month, d.day, tzinfo=pytz.utc)


def convert_to_utc_end_of_day(d: Union[date, datetime]) -> datetime:
    """
    Convert the date to a datetime at the end of that day in UTC

    >>> str(convert_to_utc_end_of_day(datetime(2023, 1, 1)))
    '2023-01-01 23:59:59.999999+00:00'

    @param d: A date
    @return: A datetime which represents the last moment of that day in UTC
    """
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=pytz.utc)


def datetime_to_date(d: Union[date, datetime]) -> date:
    if isinstance(d, (datetime, python_datetime)):
        return d.date()
    return d


def make_hashable(x):
    if isinstance(x, dict):
        return HashableDict(x)
    if isinstance(x, Iterable) and not isinstance(x, (tuple, str)):
        return tuple([make_hashable(v) for v in x])
    return x


def markdown_escape(s: str) -> str:
    return s.replace("*", "\\*").replace("_", "\\_")


def format_session_url(base_url, country_code, party_id, session_id):
    return urljoin(
        with_trailing_slash(base_url), "/".join([country_code, party_id, session_id])
    )


def hours_to_milliseconds(total_time_float: float) -> int:
    return int(total_time_float * 3600 * 1000)
