import orjson
from datetime import datetime
from enum import Enum

def custom_orjson_dumps(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Type {type(obj)} is not serializable")

def orjson_serializer(obj):
    return orjson.dumps(obj, default=custom_orjson_dumps).decode()