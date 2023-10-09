from rest_framework import serializers

from ocpi22.locations.serializers import LocationSerializer221, EvseSerializer
from ocpi22.models.location import Evse, Connector
from ocpi22.models.session import Session
from ocpi22.ocpi.serializers import LocationIdSerializer
from util import default_error_messages


class ConnectorSerializer(serializers.Serializer):
    def to_representation(self, instance: Session):
        return instance.connector.uid if hasattr(instance, 'connector') and instance.connector else None

    def to_internal_value(self, connector_id: str):
        evse_uid = self.parent.initial_data.get('evse')
        location_id = self.parent.initial_data.get('location')
        connector = Connector.get_if_exists(uid=connector_id, evse__uid=evse_uid, evse__location__uid=location_id)
        if not connector:
            self.fail('object_missing', name='Connector', uid=connector_id)
        return connector


class EvseIdSerializer(serializers.Serializer):
    default_error_messages = default_error_messages

    def to_representation(self, instance):
        return instance.evse.uid if hasattr(instance, 'evse') and instance.evse else None

    def to_internal_value(self, data):
        evse = Evse.get_if_exists(uid=data, location__uid=self.parent.initial_data.get('location'))
        if not evse:
            self.fail('object_missing', name='EVSE', uid=data)
        return evse


class StartSessionSerializer(serializers.Serializer):
    location = LocationIdSerializer()
    evse = EvseIdSerializer()
    connector = ConnectorSerializer()
