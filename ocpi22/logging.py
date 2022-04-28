import logging

from django.conf import settings


def log_error(request, s: str) -> None:
    logging.error(f'{s} ({request.credentials.party() if hasattr(request, "credentials") else "?"} '
                  f'=> {settings.HOSTNAME})')
