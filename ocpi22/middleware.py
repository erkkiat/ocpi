import json
import logging
from json import JSONDecodeError
from pprint import pprint

from django.http import JsonResponse
from rest_framework import status
from django.conf import settings

from ocpi22.ocpi.auth import OCPIPermission, check_auth_token
from ocpi22.ocpi.util import format_ocpi_response, get_to_party
from ocpi22.routing import route_ocpi_request
from ocpi22.util import is_our_identifier


class OCPIHubMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        if hasattr(request, 'body'):
            to = None
            try:
                headers = request.META
                to = get_to_party(headers)
                # ic(party)
                if to:
                    # Todo: Check that Command has the same Party as Credentials (maybe in auth.py)
                    if not is_our_identifier(to):
                        # Do some routing
                        permissions = OCPIPermission()
                        token = permissions.get_token(request)
                        if check_auth_token(request, token):
                            return route_ocpi_request(request, to)
                        else:
                            return JsonResponse(
                                data=format_ocpi_response(status_message=f'Token "{token}" not recognized',
                                                          status_code=2000),
                                status=status.HTTP_401_UNAUTHORIZED
                            )
                    else:
                        # No routing needed, message is for us
                        logging.info(f'{to} is ours, no routing done')

            except JSONDecodeError:
                # Ok, it's not JSON, we can't route it over OCPI
                pass
            except Exception as e:
                logging.error(f'{settings.HOSTNAME}: Unable to route to {to if to else ""}: {e}')
                return JsonResponse(
                    data=format_ocpi_response(status_message=f'Unable to route this message due to unknown reason',
                                              status_code=2000),
                    status=status.HTTP_400_BAD_REQUEST
                )

        response = self.get_response(request)
        return response


class DebugMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.

        logging.info(request, request.headers)

        if hasattr(request, 'body'):
            try:
                if request and request.body:
                    pprint(request.headers)
                    pprint(json.loads(request.body))
            except:
                print('Cannot print request.body as json')

        response = self.get_response(request)

        # Code to be executed for each request/response after
        # the view is called.

        return response
