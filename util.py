import hashlib
import json
from typing import List, Any

from django.urls import NoReverseMatch
from rest_framework.reverse import reverse as django_reverse

from ocpi22 import choices


class OCPIVersion:
    def __init__(self, version):
        """
        >>> OCPIVersion('2.1.1')
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
        """
        if isinstance(version, OCPIVersion):
            version = str(version.version)
        else:
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
    target = f' target="{target}" ' if target else ''
    return f'<a{target} href="{href}">{text}</a>'


def format_url(url, **kwargs) -> str:
    """
    >>> format_url("https://fakehost/start/{evse_id}/", evse_id=1)
    'https://fakehost/start/1/'
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
    attr_dict = vars(obj)
    attr_dict = attr_dict.copy()
    attr_dict.pop('_state', None)
    # Convert the dictionary to a string and hash it
    attr_str = json.dumps(attr_dict, sort_keys=True, default=str)
    thehash = int(hashlib.sha256(attr_str.encode()).hexdigest(), 16)
    return thehash
