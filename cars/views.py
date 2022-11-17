from django.core.handlers.wsgi import WSGIRequest
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.reverse import reverse

from cars.cars import search, get_models
from ocpi22.models.location import Location


class CarsViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    publicly_visible = True

    queryset = Location.objects.none()  # To determine access

    def list(self, request, *args, **kwargs) -> Response:
        return Response(
            dict(
                autocomplete=request.build_absolute_uri(
                    reverse('msp-cars-autocomplete')
                ),
                autocomplete_example=request.build_absolute_uri(
                    f"{reverse('msp-cars-autocomplete')}?q=model3"
                ),
                car_details=request.build_absolute_uri(
                    reverse('msp-cars-model')
                ),
            )
        )

    @action(methods=['GET'], detail=False)
    def autocomplete(_self, request: WSGIRequest):
        """
        This autocomplete is used for the input field where the EV driver types their car brand/model.
        Store the resulting ID to be saved in the user profile.

        The format is suitable for jquery. Please request for any additional formats.
        """
        query = request.GET.get('q')
        if not query:
            return Response(dict(
                status_message='Please specify a user typed car brand/model substring with query parameter ?q=substr'))
        return Response(dict(data=[dict(value=car.full_name, id=car.id) for car in search(query)]))

    @action(methods=['GET'], detail=False, url_path='model(?:/(?P<id>[^/.]+))?')
    def model(_self, request: WSGIRequest, id=None):
        if not id:
            args = ["tesla-model-s-100d"]
            return Response(
                dict(
                    status_message=f'Please specify the car model you got from autocomplete, '
                                   f'for example {request.build_absolute_uri(reverse("msp-cars-model", args=args))}'
                )
            )
        car = get_models().get(id)
        if not car:
            return Response(dict(status_message='No car found with the given id.'), status=status.HTTP_404_NOT_FOUND)
        return Response(dict(data=car.original_json))
