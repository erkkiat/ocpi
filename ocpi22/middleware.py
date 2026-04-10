import json

import redis

import ocpi22.ocpi_logging as logging
from json import JSONDecodeError
from pprint import pprint

from django.http import JsonResponse, HttpResponse
from rest_framework import status

from ocpi22.ocpi.auth import OCPIPermission, check_auth_token
from ocpi22.ocpi.util import format_ocpi_response
from ocpi22.ocpi.util_party import get_sender_party, get_to_party
from ocpi22.routing import route_ocpi_request
from ocpi22.util import is_our_identifier


class OCPIHubMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        if hasattr(request, "body"):
            to = None
            try:
                headers = request.META
                to = get_to_party(headers)
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
                                data=format_ocpi_response(
                                    status_message=f'Token "{token}" not recognized',
                                    status_code=2000,
                                ),
                                status=status.HTTP_401_UNAUTHORIZED,
                            )
                    else:
                        # No routing needed, message is for us
                        logging.info(f"{to} is ours, no routing done")

            except JSONDecodeError:
                # Ok, it's not JSON, we can't route it over OCPI
                pass
            except Exception as e:
                logging.error(f"Unable to route to {to if to else ''}: {e}")
                return JsonResponse(
                    data=format_ocpi_response(
                        status_message="Unable to route this message due to unknown reason",
                        status_code=2000,
                    ),
                    status=status.HTTP_400_BAD_REQUEST,
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

        if hasattr(request, "body"):
            try:
                if request and request.body:
                    # TODO: let's not use print/pprint we will log them
                    pprint(request.headers)
                    pprint(json.loads(request.body))
            except Exception as e:  # noqa
                print("Cannot print request.body as json")

        response = self.get_response(request)

        # Code to be executed for each request/response after
        # the view is called.

        return response


class ErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
            if response.status_code >= 405:
                try:
                    party = get_sender_party(request.META)
                except ValueError:
                    party = None
                if party:
                    logging.error(
                        f"Returning status code {response.status_code} for party {str(party)}."
                    )
                else:
                    logging.error(
                        f"Returning status code {response.status_code} for user {request.user}."
                    )

            return response
        except redis.exceptions.ConnectionError as e:
            logging.error(f"Unable to connect to Redis: {e}", request)
            raise
        except ConnectionRefusedError as e:
            logging.error(f"An external connection was refused: {e}", request)
            raise
        except Exception as e:
            logging.error(f"An exception occured: {e}", request)
            raise


class OCPI221HeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response: HttpResponse = self.get_response(request)

        for request_key, response_key in (
            ("X-Request-ID", "X-Request-ID"),
            ("X-Correlation-ID", "X-Correlation-ID"),
            ("OCPI-To-Party-Id", "OCPI-From-Party-Id"),
            ("OCPI-To-Country-Code", "OCPI-From-Country-Code"),
            ("OCPI-From-Party-Id", "OCPI-To-Party-Id"),
            ("OCPI-From-Country-Code", "OCPI-To-Country-Code"),
        ):
            response.headers[response_key] = request.headers.get(request_key, "")

        return response
