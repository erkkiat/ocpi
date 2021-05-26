from django.contrib.auth.models import User, Group
from rest_framework import serializers

from ocpi22.models import Location


def serialize_location(l: Location):
    return dict(
        country_code=l.country_code,
        party_id=l.party_id,
        id=l.uid,
        publish=l.publish,
        # publish_allowed_to=serialize_publish_allowed_to(l.publish_allowed_to),
        name=l.name or '',
        address=l.address,
        city=l.city,
        postal_code=l.postal_code or '',
        state=l.state,
        country=l.country,
        coordinates=dict(
            latitude=l.latitude,
            longitude=l.longitude
        ),
        parking_type=l.parking_type or '',
        # operator=serialize_businessdetails(l.operator),
        # suboperator=serialize_businessdetails(l.suboperator),
        # owner=serialize_businessdetails(l.owner),
        # Facilities, etc.
    )


# class UserSerializer(serializers.HyperlinkedModelSerializer):
#     class Meta:
#         model = User
#         fields = ['url', 'username', 'email', 'groups']
#
#
# class GroupSerializer(serializers.HyperlinkedModelSerializer):
#     class Meta:
#         model = Group
#         fields = ['url', 'name']
