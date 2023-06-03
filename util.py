from django.urls import NoReverseMatch
from rest_framework.reverse import reverse as django_reverse


def reverse(s, args=[], request=None, version=None) -> str:
    version = version or request.version if request else '2.2.1'
    version_args = [version, *args]
    try:
        return django_reverse(s, args=version_args, request=request)
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
