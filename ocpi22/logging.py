import logging

from django.conf import settings


def log_error(request=None, s: str = None) -> None:
    logging.error(f'{s} ({request.credentials.party() if request and hasattr(request, "credentials") else "?"} '
                  f'=> {settings.HOSTNAME})')
