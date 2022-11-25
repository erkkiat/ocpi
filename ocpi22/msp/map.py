from geojson import GeometryCollection, Point, Feature
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ocpi22.models.location import Location


class MapViewSet(viewsets.GenericViewSet):
    publicly_visible = True

    def options(self, _request):
        return Response(dict(
            status='Please see https://tools.ietf.org/html/rfc7946.')
        )

    @action(methods=['GET'], detail=False)
    def locations(self, _request):
        geometry = GeometryCollection(
            [Feature(
                geometry=Point((location.latitude, location.longitude)),
                properties=dict(
                    location=dict(
                        uid=location.uid,
                        name=location.name,
                        address=location.address,
                        city=location.city,
                        country=location.country,
                        connectors_available=location.available(),
                    ),
                    evses=[
                        dict(
                            uid=evse.uid,
                            evse_id=evse.evse_id,
                            status=evse.status,
                            connectors=[dict(
                                uid=connector.uid,
                                standard=connector.standard,
                                power=connector.max_electric_power,
                                price=connector.tariff(),
                            ) for connector in evse.connectors.all()]
                        ) for evse in location.evses.all()
                    ],
                )
            ) for location in Location.objects.all()]
        )
        return Response(geometry, headers={'content-type': 'application/json; charset=UTF-8'})
