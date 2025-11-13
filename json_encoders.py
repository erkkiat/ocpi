import orjson
from datetime import datetime
from enum import Enum


def serialize_datetime_and_enum_to_string(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Type {type(obj)} is not serializable")


def orjson_serializer(obj):
    return orjson.dumps(obj, default=serialize_datetime_and_enum_to_string).decode()
