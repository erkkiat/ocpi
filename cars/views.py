from django.core.handlers.wsgi import WSGIRequest
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from cars.cars import search
from ocpi22.models.location import Location


class CarsViewSet(ViewSet):
    queryset = Location.objects.none()  # To determine access

    @action(methods=['GET'], detail=False)
    def autocomplete(_self, request: WSGIRequest):
        """
        This autocomplete is used for the input field where the EV driver types their car brand/model.
        Store the resulting ID to be saved in the user profile.
        """
        query = request.GET.get('q')
        if not query:
            return Response(dict(
                status_message='Please specify a user typed car brand/model substring with query parameter ?q=substr'))
        return Response(dict(data=[dict(value=car.full_name, id=car.id) for car in search(query)]))
