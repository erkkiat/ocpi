import json
from datetime import datetime

import redis
from django.conf import settings
from django.shortcuts import render

import ocpi22.logging as logging
from json import JSONDecodeError
from pprint import pprint

from django.http import JsonResponse
from rest_framework import status

from ocpi22.ocpi.auth import OCPIPermission, check_auth_token
from ocpi22.ocpi.util import format_ocpi_response
from ocpi22.ocpi.util_party import get_sender_party, get_to_party
from ocpi22.routing import route_ocpi_request
from ocpi22.util import is_our_identifier

# For profiling
import cProfile
import pstats
import io
from django.utils.deprecation import MiddlewareMixin


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
                logging.error(f'Unable to route to {to if to else ""}: {e}')
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


class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            logging.log_user_activity(request.user.username)
        else:
            party = get_sender_party(request.META)
            if party:
                logging.log_ocpi_activity(str(party))

        response = self.get_response(request)
        return response


class ErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
            if response.status_code >= 405:
                party = get_sender_party(request.META)
                if party:
                    logging.error(f'Returning status code {response.status_code} for party {str(party)}.')
                else:
                    logging.error(f'Returning status code {response.status_code} for user {request.user}.')

            return response
        except redis.exceptions.ConnectionError as e:
            logging.error(f'Unable to connect to Redis: {e}', request)
            raise
        except ConnectionRefusedError as e:
            logging.error(f'An external connection was refused: {e}', request)
            raise
        except Exception as e:
            logging.error(f'An exception occured: {e}', request)
            raise


class ProfilerMiddleware(MiddlewareMixin):
    def process_request(self, request):
        setattr(self, 'pr', cProfile.Profile())
        self.pr.enable()

    def process_response(self, request, response):
        self.pr.disable()
        self.pr.dump_stats('profile_output.prof')
        # s = io.StringIO()
        # sortby = pstats.SortKey.CUMULATIVE
        # ps = pstats.Stats(self.pr, stream=s).sort_stats(sortby)
        # ps.print_stats()
        # print(s.getvalue())
        return response


class EnabledUntilMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        now = datetime.now()
        if now > settings.EXPIRES_ON:
            logging.error(f'Someone is trying to access an expired instance, expired since {settings.EXPIRES_ON}',
                          request)
            return render(request, 'expired.html', {'expires_on': settings.EXPIRES_ON})
        response = self.get_response(request)
        return response


REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'status_code'])
REQUEST_LATENCY = Histogram('http_request_latency_seconds', 'HTTP request latency', ['method', 'endpoint'])


class PrometheusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        REQUEST_COUNT.labels(request.method, request.path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, request.path).observe(response.elapsed.total_seconds() if hasattr(response, 'elapsed') else 0)
        return response

    @staticmethod
    def metrics_view(request):
        metrics_page = generate_latest()
        return HttpResponse(metrics_page, content_type=CONTENT_TYPE_LATEST)
