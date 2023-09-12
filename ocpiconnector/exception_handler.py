from functools import wraps

from django.db import IntegrityError
from django.http import HttpRequest
from rest_framework import status
from rest_framework.exceptions import ValidationError, NotFound

from ocpi22.ocpi.util import OCPIBadRequestResponse, Ocpi
from ocpiconnector.exceptions import WrongRole


def find_request_from_args(*args, **kwargs):
    """
    Find a HttpRequest in the args or kwargs.
    """
    if 'request' in kwargs:
        return kwargs['request']
    for arg in args:
        if isinstance(arg, HttpRequest):
            return arg


def ocpi_exception_handler(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        from ocpi22 import logging
        from ocpi22.models.location import Evse, Location, Connector
        from ocpi22.models.session import Session
        from ocpi22.models.token import Token
        from ocpi22.models.tariff import Tariff

        EXCEPTION_MAPPINGS = {
            Location.DoesNotExist:
                dict(msg='Cannot find a Location with the specified ID: {}',
                     status_code=Ocpi.ClientError.UNKNOWN_LOCATION),
            Evse.DoesNotExist:
                dict(msg='The specified EVSE does not exist in the specified Location: {}',
                     status_code=Ocpi.ClientError.UNKNOWN_LOCATION),
            Connector.DoesNotExist:
                dict(msg='Cannot find the specified Connector at specified Location: {}',
                     status_code=Ocpi.ClientError.UNKNOWN_LOCATION),
            Session.DoesNotExist:
                dict(msg='Cannot find the specified Session: {}'),
            Token.DoesNotExist:
                dict(msg='Cannot find the specified Token: {}'),
            Tariff.DoesNotExist:
                dict(msg='Cannot find the specified Tariff: {}'),
            NotFound:
                dict(msg='Cannot find the specified object: {}'),
            ValidationError:
                dict(msg='Validation error: {}',
                     status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                     http_status=status.HTTP_400_BAD_REQUEST),
            IntegrityError:
                dict(msg='Database integrity error: {}',
                     status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                     http_status=status.HTTP_400_BAD_REQUEST),
            KeyError:
                dict(msg='Key error: {}',
                     status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                     http_status=status.HTTP_400_BAD_REQUEST),
            AssertionError:
                dict(msg='Some data is not matching requirements: {}',
                     status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                     http_status=status.HTTP_400_BAD_REQUEST),
            ValueError:
                dict(msg='ValueError: {}',
                     status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
                     http_status=status.HTTP_400_BAD_REQUEST),
            WrongRole:
                dict(msg='You need a specific role in order to do that: {}',
                     status_code=Ocpi.ClientError.GENERIC_CLIENT_ERROR,
                     http_status=status.HTTP_400_BAD_REQUEST),
        }

        try:
            return func(*args, **kwargs)

        except tuple(EXCEPTION_MAPPINGS.keys()) as e:
            result = EXCEPTION_MAPPINGS[type(e)]
            error_message = result.get('msg', 'Error: {}').format(e)
            return OCPIBadRequestResponse(str(e),
                status_message=error_message,
                status_code=result.get('status_code', Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS),
                http_status=result.get('http_status', status.HTTP_404_NOT_FOUND),
            )

    return wrapper

