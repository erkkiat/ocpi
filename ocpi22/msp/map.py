from geojson import Point, Feature, FeatureCollection
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ocpi22.models.location import Location


def flatten_for_geojson(elements: dict, name=None) -> dict:
    """
    Flatten a dict for geojson properties.
    >>> flatten_for_geojson(dict(level1a=dict(level2=dict(level3='value')), level1b='value2'))
    {'level1a:level2:level3': 'value', 'level1b': 'value2'}
    >>> flatten_for_geojson(dict(level1a=dict(level2=[dict(level3='value1a'), dict(level3='value1b')]), level1b='value2'))
    {'level1a:level2:0:level3': 'value1a', 'level1a:level2:1:level3': 'value1b', 'level1b': 'value2'}
    """
    result = {}
    for element in elements:
        if name:
            full_name = f'{name}:{element}'
        else:
            full_name = element
        if isinstance(elements[element], dict):
            result.update(flatten_for_geojson(elements[element], full_name))
        elif isinstance(elements[element], list):
            for index, item in enumerate(elements[element]):
                result.update(flatten_for_geojson(item, f'{full_name}:{index}'))
        else:
            result[f'{full_name}'] = elements.get(element)
    return result


class MapViewSet(viewsets.GenericViewSet):
    publicly_visible = True

    def options(self, _request):
        return Response(dict(
            status='Please see https://tools.ietf.org/html/rfc7946.')
        )

    @action(methods=['GET'], detail=False)
    def locations(self, _request):
        # You can paste the geojson output in https://geojson.io/ to visualize it.

        geometry = FeatureCollection(
            [Feature(
                geometry=Point((location.longitude, location.latitude)),
                properties=flatten_for_geojson(dict(
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
            )) for location in Location.objects.all()]
        )
        return Response(geometry, headers={'content-type': 'application/json; charset=UTF-8'})
