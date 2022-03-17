import json
import logging
from json import JSONDecodeError
from pprint import pprint

from icecream import ic

from ocpi22.ocpi_util import ocpi_route_request
from ocpi22.util import is_our_identifier
from ocpiconnector.ocpi_identities import Party


class OCPIHubMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        if hasattr(request, 'body'):
            try:
                headers = request.headers
                to = Party(headers.get('Ocpi-To-Country-Code'), headers.get('Ocpi-To-Party-Id'))
                # ic(party)
                if to:
                    if not is_our_identifier(to):
                        return ocpi_route_request(request, to)
                    else:
                        logging.info(f'{to} is ours, no routing done')
            except JSONDecodeError:
                # Ok, it's not JSON, we can't route it over OCPI
                pass
            except Exception as e:
                logging.error(f'Unable to route to {to}: {e}')
                # return Response('Hub is unable to route this request due to its malformed json data')

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
