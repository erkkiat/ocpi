from django.urls import NoReverseMatch
from rest_framework.reverse import reverse as django_reverse


def reverse(s, args=[], request=None, version=None) -> str:
    version = version or request.version if request else '2.2.1'
    version_args = [version, *args]
    try:
        return django_reverse(s, args=version_args, request=request)
    except NoReverseMatch:
        return django_reverse(s, args=args, request=request)
