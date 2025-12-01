import pytest
from datetime import datetime
from enum import Enum
from json_encoders import orjson_serializer


class Color(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


def test_serialize_datetime():
    dt = datetime(2024, 11, 6, 13, 6, 43)
    expected = f'"{dt.isoformat()}"'
    assert orjson_serializer(dt) == expected


def test_serialize_enum():
    color = Color.RED
    expected = f'"{color.value}"'
    assert orjson_serializer(color) == expected


def test_serialize_dict_with_custom_types():
    dt = datetime(2024, 11, 6, 13, 6, 43)
    color = Color.GREEN
    data = {"timestamp": dt, "color": color, "value": 42}
    expected = f'{{"timestamp":"{dt.isoformat()}","color":"{color.value}","value":42}}'
    assert orjson_serializer(data) == expected


def test_serialize_unsupported_type():
    class Unsupported:
        pass

    with pytest.raises(TypeError):
        orjson_serializer(Unsupported())
