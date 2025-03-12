from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from ocpi22.models.location import Evse
from ocpi22.ocpi import util
from ocpi22.ocpi.util import remove_none_values_recursively_from_dict
from ocpi22.tests.factories import EvseFactory


@pytest.fixture
def evse_queryset():
    with patch("ocpi22.util.is_our_identifier") as mock_is_ours:
        mock_is_ours.return_value = False
        EvseFactory(
            last_updated=datetime(2025, 1, 1, 12, 00, 00, tzinfo=ZoneInfo("UTC"))
        )
        EvseFactory(
            last_updated=datetime(2025, 1, 1, 13, 00, 00, tzinfo=ZoneInfo("UTC"))
        )
        EvseFactory(
            last_updated=datetime(2025, 1, 2, 12, 00, 00, tzinfo=ZoneInfo("UTC"))
        )
        EvseFactory(
            last_updated=datetime(2025, 1, 2, 13, 00, 00, tzinfo=ZoneInfo("UTC"))
        )

        return Evse.objects.all()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "date_from, date_to, expected_count",
    [
        (
            "2025-01-01 11:59:59",
            None,
            4,
        ),  # Test: Returns success queryset after a certain date_from
        ("2025-01-01 12:00:01", None, 3),  # Test: Returns only three records
        ("2026-01-03 12:00:01", None, 0),  # Test: Future date_from returns zero records
        (None, "2020-01-03 12:00:01", 0),  # Test: Past date_to returns zero records
        (None, "2025-01-03 12:00:01", 4),  # Test: date_to returns all records
        (None, "2020-01-02 12:00:01", 0),  # Test: date_to returns only three records
        ("2025-01-01 12:00:01", "2025-01-02 12:00:01", 2),  # Test: returns 2 records
        (
            "2026-01-03 12:00:01",
            "2020-01-03 11:59:59",
            0,
        ),  # Test: Past date_to and Future date_from
    ],
)
def test_applying_ocpi22_filters(evse_queryset, date_from, date_to, expected_count):
    mock_request = Mock()
    mock_request.GET = {"date_from": date_from, "date_to": date_to}

    result = util.apply_ocpi22_filters(mock_request, evse_queryset)

    assert result.count() == expected_count


def test_remove_none_values_recursively_from_dict_success():
    data = {
        "key1": "value1",
        "key2": None,
        "key3": {
            "subkey1": "subvalue1",
            "subkey2": None,
            "subkey3": {"subsubkey1": "subsubvalue1", "subsubkey2": None},
        },
        "key4": [None, "listvalue1", {"listkey1": None, "listkey2": "listvalue2"}],
    }

    expected_result = {
        "key1": "value1",
        "key3": {"subkey1": "subvalue1", "subkey3": {"subsubkey1": "subsubvalue1"}},
        "key4": ["listvalue1", {"listkey2": "listvalue2"}],
    }

    result = remove_none_values_recursively_from_dict(data)

    assert result == expected_result


def test_remove_none_values_recursively_from_an_empty_dict():
    data = {}

    expected_result = {}

    result = remove_none_values_recursively_from_dict(data)
    assert result == expected_result


def test_remove_none_values_recursively_from_an_empty_list():
    data = []

    expected_result = []

    result = remove_none_values_recursively_from_dict(data)
    assert result == expected_result
