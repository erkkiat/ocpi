from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError

from ocpi22.models.location import Evse
from ocpi22.ocpi import util
from ocpi22.tests.factories import EvseFactory
from ocpi22.util import uid_validator


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


def test_uid_validator_allows_underscore():
    uid_validator("valid_uid_123")


def test_uid_validator_does_not_allow_special_chars():
    with pytest.raises(ValidationError):
        uid_validator("valid?uid?123")
