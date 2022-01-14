import json

from icecream import ic


class DebugMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.

        ic()
        ic(request)

        if hasattr(request, 'body'):
            try:
                ic(json.loads(request.body))
            except:
                print('Cannot print request.body as json')
                ic(request.body)

        response = self.get_response(request)

        # Code to be executed for each request/response after
        # the view is called.

        return response
