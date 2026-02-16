"""
Tests for DirectPayment Serializers

Tests spec compliance for coordinates and total_cost nested objects.
"""

import pytest
from django.utils import timezone

from ocpi22.payments.serializers import (
    GeoLocationSerializer,
    PriceSerializer,
    TerminalSerializer,
    TerminalWriteSerializer,
    FinancialAdviceConfirmationSerializer,
    FinancialAdviceConfirmationWriteSerializer,
)


class TestGeoLocationSerializer:
    @pytest.mark.parametrize(
        "latitude,longitude",
        [
            ("52.372294", "4.898632"),
            ("60.169857", "24.938379"),
            ("-33.86882", "151.20929"),
            ("0.00", "0.00"),
        ],
    )
    def test_geolocation_serializer_accepts_valid_coordinates(
        self, latitude, longitude
    ):
        data = {"latitude": latitude, "longitude": longitude}
        serializer = GeoLocationSerializer(data=data)

        assert serializer.is_valid()
        assert serializer.validated_data["latitude"] == latitude
        assert serializer.validated_data["longitude"] == longitude

    @pytest.mark.parametrize(
        "latitude,longitude,expected_error_field",
        [
            ("invalid", "4.898632", "latitude"),
            ("52.372294", "invalid", "longitude"),
            ("91.0", "4.898632", "latitude"),
            ("52.372294", "181.0", "longitude"),
        ],
    )
    def test_geolocation_serializer_rejects_invalid_coordinates(
        self, latitude, longitude, expected_error_field
    ):
        data = {"latitude": latitude, "longitude": longitude}
        serializer = GeoLocationSerializer(data=data)

        assert not serializer.is_valid()
        assert expected_error_field in serializer.errors


class TestPriceSerializer:
    @pytest.mark.parametrize(
        "excl_vat,incl_vat,currency",
        [
            (10.50, 12.60, "EUR"),
            (0.00, 0.00, "USD"),
            (100.00, None, "GBP"),
            (50.25, 60.30, "NOK"),
        ],
    )
    def test_price_serializer_accepts_valid_data(self, excl_vat, incl_vat, currency):
        data = {"excl_vat": excl_vat, "currency": currency}
        if incl_vat is not None:
            data["incl_vat"] = incl_vat

        serializer = PriceSerializer(data=data)

        assert serializer.is_valid()
        assert serializer.validated_data["excl_vat"] == excl_vat
        assert serializer.validated_data["currency"] == currency

    def test_price_serializer_rejects_data_when_excl_vat_missing(self):
        data = {"currency": "EUR"}
        serializer = PriceSerializer(data=data)

        assert not serializer.is_valid()
        assert "excl_vat" in serializer.errors

    def test_price_serializer_rejects_data_when_currency_missing(self):
        data = {"excl_vat": 10.50}
        serializer = PriceSerializer(data=data)

        assert not serializer.is_valid()
        assert "currency" in serializer.errors


@pytest.mark.django_db
class TestTerminalSerializerNestedCoordinates:
    def test_terminal_serializer_converts_incoming_nested_coordinates_to_internal_flat_format(
        self,
    ):
        data = {
            "terminal_id": "TERM001",
            "customer_reference": "CUST001",
            "coordinates": {"latitude": "52.372294", "longitude": "4.898632"},
        }

        serializer = TerminalWriteSerializer(data=data)

        assert serializer.is_valid(), f"Validation failed: {serializer.errors}"
        validated = serializer.validated_data
        assert validated["latitude"] == "52.372294"
        assert validated["longitude"] == "4.898632"
        assert "coordinates" not in validated

    def test_terminal_serializer_rejects_incoming_coordinates_when_latitude_invalid(
        self,
    ):
        data = {
            "terminal_id": "TERM003",
            "customer_reference": "CUST003",
            "coordinates": {"latitude": "invalid", "longitude": "4.898632"},
        }

        serializer = TerminalWriteSerializer(data=data)

        assert not serializer.is_valid()
        assert "coordinates" in serializer.errors
        assert "latitude" in serializer.errors["coordinates"]

    def test_terminal_serializer_returns_outgoing_coordinates_as_nested_object(
        self, db_terminal
    ):
        terminal = db_terminal(
            terminal_id="TERM004",
            customer_reference="CUST004",
            latitude="52.372294",
            longitude="4.898632",
        )

        serializer = TerminalSerializer(terminal)
        data = serializer.data

        assert "coordinates" in data
        assert data["coordinates"]["latitude"] == "52.372294"
        assert data["coordinates"]["longitude"] == "4.898632"

    def test_terminal_serializer_omits_coordinates_when_latitude_and_longitude_missing(
        self, db_terminal
    ):
        terminal = db_terminal(
            terminal_id="TERM005",
            customer_reference="CUST005",
            latitude=None,
            longitude=None,
        )

        serializer = TerminalSerializer(terminal)
        data = serializer.data

        assert "coordinates" not in data


@pytest.mark.django_db
class TestFACSerializerNestedTotalCost:
    def test_fac_serializer_converts_incoming_nested_total_cost_to_internal_flat_format(
        self,
    ):
        data = {
            "fac_id": "FAC001",
            "authorization_reference": "AUTH001",
            "total_cost": {"excl_vat": 10.50, "incl_vat": 12.60, "currency": "EUR"},
            "eft_data": ["EFT_DATA_1"],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationWriteSerializer(data=data)

        assert serializer.is_valid(), f"Validation failed: {serializer.errors}"
        validated = serializer.validated_data
        assert validated["total_cost_excl_vat"] == 10.50
        assert validated["total_cost_incl_vat"] == 12.60
        assert validated["currency"] == "EUR"
        assert "total_cost" not in validated

    def test_fac_serializer_rejects_incoming_flat_total_cost_fields(self):
        data = {
            "fac_id": "FAC002",
            "authorization_reference": "AUTH002",
            "total_cost_excl_vat": 20.00,
            "total_cost_incl_vat": 24.00,
            "currency": "USD",
            "eft_data": ["EFT_DATA_2"],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationWriteSerializer(data=data)

        assert not serializer.is_valid()
        assert "total_cost" in serializer.errors

    def test_fac_serializer_rejects_incoming_total_cost_when_excl_vat_invalid(self):
        data = {
            "fac_id": "FAC003",
            "authorization_reference": "AUTH003",
            "total_cost": {"excl_vat": "invalid", "currency": "EUR"},
            "eft_data": ["EFT_DATA_3"],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationWriteSerializer(data=data)

        assert not serializer.is_valid()
        assert "total_cost" in serializer.errors
        assert "excl_vat" in serializer.errors["total_cost"]

    def test_fac_serializer_accepts_incoming_total_cost_without_incl_vat(self):
        data = {
            "fac_id": "FAC004",
            "authorization_reference": "AUTH004",
            "total_cost": {"excl_vat": 30.00, "currency": "NOK"},
            "eft_data": ["EFT_DATA_4"],
            "capture_status_code": "FAILED",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationWriteSerializer(data=data)

        assert serializer.is_valid(), f"Validation failed: {serializer.errors}"
        validated = serializer.validated_data
        assert validated["total_cost_excl_vat"] == 30.00
        assert validated.get("total_cost_incl_vat") is None
        assert validated["currency"] == "NOK"

    def test_fac_serializer_returns_outgoing_total_cost_as_nested_object(self, db_fac):
        fac = db_fac(
            fac_id="FAC005",
            authorization_reference="AUTH005",
            total_cost_excl_vat=10.50,
            total_cost_incl_vat=12.60,
            currency="EUR",
            eft_data=["DATA"],
            capture_status_code="SUCCESS",
            last_updated=timezone.now(),
        )

        serializer = FinancialAdviceConfirmationSerializer(fac)
        data = serializer.data

        assert "total_cost" in data
        assert data["total_cost"]["excl_vat"] == 10.50
        assert data["total_cost"]["incl_vat"] == 12.60
        assert data["total_cost"]["currency"] == "EUR"

    def test_fac_serializer_returns_outgoing_total_cost_without_incl_vat_when_null(
        self, db_fac
    ):
        fac = db_fac(
            fac_id="FAC006",
            authorization_reference="AUTH006",
            total_cost_excl_vat=50.00,
            total_cost_incl_vat=None,
            currency="USD",
            eft_data=["DATA"],
            capture_status_code="SUCCESS",
            last_updated=timezone.now(),
        )

        serializer = FinancialAdviceConfirmationSerializer(fac)
        data = serializer.data

        assert "total_cost" in data
        assert data["total_cost"]["excl_vat"] == 50.00
        assert "incl_vat" not in data["total_cost"]
        assert data["total_cost"]["currency"] == "USD"


@pytest.mark.django_db
class TestRoundtripConversion:
    def test_terminal_serializer_roundtrip_converts_nested_coordinates_to_flat_and_back(
        self, db_terminal
    ):
        incoming_data = {
            "terminal_id": "TERM_RT001",
            "customer_reference": "CUST_RT001",
            "coordinates": {"latitude": "60.169857", "longitude": "24.938379"},
            "address": "Mannerheimintie 1",
            "city": "Helsinki",
            "country": "FIN",
        }

        write_serializer = TerminalWriteSerializer(data=incoming_data)
        assert write_serializer.is_valid()

        validated = write_serializer.validated_data
        terminal = db_terminal(**validated)

        read_serializer = TerminalSerializer(terminal)
        outgoing_data = read_serializer.data

        assert outgoing_data["coordinates"]["latitude"] == "60.169857"
        assert outgoing_data["coordinates"]["longitude"] == "24.938379"

    def test_fac_serializer_roundtrip_converts_nested_total_cost_to_flat_and_back(
        self, db_fac
    ):
        incoming_data = {
            "fac_id": "FAC_RT001",
            "authorization_reference": "AUTH_RT001",
            "total_cost": {"excl_vat": 45.50, "incl_vat": 56.65, "currency": "EUR"},
            "eft_data": ["DATA1", "DATA2"],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        write_serializer = FinancialAdviceConfirmationWriteSerializer(
            data=incoming_data
        )
        assert write_serializer.is_valid()

        validated = write_serializer.validated_data
        fac = db_fac(**validated)

        read_serializer = FinancialAdviceConfirmationSerializer(fac)
        outgoing_data = read_serializer.data

        assert outgoing_data["total_cost"]["excl_vat"] == 45.50
        assert outgoing_data["total_cost"]["incl_vat"] == 56.65
        assert outgoing_data["total_cost"]["currency"] == "EUR"
