import pytest
from django.utils import timezone

from ocpi22.payments.serializers import (
    GeoLocationSerializer,
    PriceSerializer,
    TerminalSerializer,
    FinancialAdviceConfirmationSerializer,
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
        "excl_vat,incl_vat",
        [
            (10.50, 12.60),
            (0.00, 0.00),
            (100.00, None),
            (50.25, 60.30),
        ],
    )
    def test_price_serializer_accepts_valid_data(self, excl_vat, incl_vat):
        data = {"excl_vat": excl_vat}
        if incl_vat is not None:
            data["incl_vat"] = incl_vat

        serializer = PriceSerializer(data=data)

        assert serializer.is_valid()
        assert serializer.validated_data["excl_vat"] == excl_vat

    def test_price_serializer_rejects_data_when_excl_vat_missing(self):
        data = {"incl_vat": 12.60}
        serializer = PriceSerializer(data=data)

        assert not serializer.is_valid()
        assert "excl_vat" in serializer.errors


@pytest.mark.django_db
class TestTerminalSerializerIncoming:
    def test_terminal_serializer_converts_incoming_nested_coordinates_to_flat_model_fields(
        self,
    ):
        data = {
            "terminal_id": "TERM001",
            "customer_reference": "TEST-CUSTOMER-REF",
            "coordinates": {"latitude": "52.372294", "longitude": "4.898632"},
            "last_updated": "2026-01-01T00:00:00Z",
        }

        serializer = TerminalSerializer(data=data)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["latitude"] == "52.372294"
        assert serializer.validated_data["longitude"] == "4.898632"
        assert "coordinates" not in serializer.validated_data

    def test_terminal_serializer_accepts_incoming_data_without_coordinates(self):
        data = {
            "terminal_id": "TERM002",
            "customer_reference": "TEST-CUSTOMER-REF",
            "last_updated": "2026-01-01T00:00:00Z",
        }

        serializer = TerminalSerializer(data=data)

        assert serializer.is_valid(), serializer.errors
        assert "latitude" not in serializer.validated_data
        assert "longitude" not in serializer.validated_data

    @pytest.mark.parametrize(
        "latitude,longitude,expected_error_field",
        [
            ("invalid", "4.898632", "latitude"),
            ("52.372294", "invalid", "longitude"),
        ],
    )
    def test_terminal_serializer_rejects_incoming_coordinates_when_coordinate_is_invalid(
        self, latitude, longitude, expected_error_field
    ):
        data = {
            "terminal_id": "TERM003",
            "coordinates": {"latitude": latitude, "longitude": longitude},
        }

        serializer = TerminalSerializer(data=data)

        assert not serializer.is_valid()
        assert "coordinates" in serializer.errors
        assert expected_error_field in serializer.errors["coordinates"]

    def test_terminal_serializer_rejects_incoming_coordinates_when_latitude_missing_but_longitude_present(
        self,
    ):
        data = {
            "terminal_id": "TERM004",
            "coordinates": {"longitude": "4.898632"},
        }

        serializer = TerminalSerializer(data=data)

        assert not serializer.is_valid()
        assert "coordinates" in serializer.errors

    @pytest.mark.parametrize("extra_field", ["location_ids", "evse_uids"])
    def test_terminal_serializer_ignores_location_and_evse_fields_in_incoming_ptp_post(
        self, extra_field
    ):
        data = {
            "terminal_id": "TERM005",
            "customer_reference": "TEST-CUSTOMER-REF",
            "last_updated": "2026-01-01T00:00:00Z",
            extra_field: ["some-uid-1", "some-uid-2"],
        }

        serializer = TerminalSerializer(data=data)

        assert serializer.is_valid(), serializer.errors
        assert extra_field not in serializer.validated_data


@pytest.mark.django_db
class TestTerminalSerializerOutgoing:
    def test_terminal_serializer_returns_outgoing_coordinates_as_spec_nested_object(
        self, db_terminal
    ):
        terminal = db_terminal(
            terminal_id="TERM010",
            latitude="52.372294",
            longitude="4.898632",
        )

        data = TerminalSerializer(terminal).data

        assert "coordinates" in data
        assert data["coordinates"]["latitude"] == "52.372294"
        assert data["coordinates"]["longitude"] == "4.898632"

    def test_terminal_serializer_omits_coordinates_from_outgoing_when_both_are_null(
        self, db_terminal
    ):
        terminal = db_terminal(
            terminal_id="TERM011",
            latitude=None,
            longitude=None,
        )

        data = TerminalSerializer(terminal).data

        assert "coordinates" not in data

    def test_terminal_serializer_includes_location_ids_and_evse_uids_in_outgoing(
        self, db_terminal
    ):
        terminal = db_terminal(terminal_id="TERM012")

        data = TerminalSerializer(terminal).data

        assert "location_ids" in data
        assert "evse_uids" in data
        assert data["location_ids"] == []
        assert data["evse_uids"] == []

    def test_terminal_serializer_includes_last_updated_in_outgoing(self, db_terminal):
        terminal = db_terminal(terminal_id="TERM013")

        data = TerminalSerializer(terminal).data

        assert "last_updated" in data
        assert data["last_updated"] is not None


@pytest.mark.django_db
class TestTerminalSerializerRoundtrip:
    def test_terminal_serializer_roundtrip_preserves_coordinates_through_nested_to_flat_to_nested(
        self, db_terminal
    ):
        incoming_data = {
            "terminal_id": "TERM_RT001",
            "customer_reference": "TEST-CUSTOMER-REF",
            "coordinates": {"latitude": "60.169857", "longitude": "24.938379"},
            "address": "Mannerheimintie 1",
            "city": "Helsinki",
            "country": "FIN",
            "last_updated": "2026-01-01T00:00:00Z",
        }

        write_serializer = TerminalSerializer(data=incoming_data)
        assert write_serializer.is_valid(), write_serializer.errors

        terminal = db_terminal(**write_serializer.validated_data)
        outgoing_data = TerminalSerializer(terminal).data

        assert outgoing_data["coordinates"]["latitude"] == "60.169857"
        assert outgoing_data["coordinates"]["longitude"] == "24.938379"
        assert outgoing_data["terminal_id"] == "TERM_RT001"


@pytest.mark.django_db
class TestFACSerializerIncoming:
    def test_fac_serializer_converts_incoming_total_costs_and_currency_to_flat_model_fields(
        self,
    ):
        data = {
            "id": "FAC001",
            "authorization_reference": "AUTH001",
            "total_costs": {"excl_vat": 10.50, "incl_vat": 12.60},
            "currency": "EUR",
            "eft_data": ["EFT_DATA_1"],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationSerializer(data=data)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["total_cost_excl_vat"] == 10.50
        assert serializer.validated_data["total_cost_incl_vat"] == 12.60
        assert serializer.validated_data["currency"] == "EUR"
        assert "total_costs" not in serializer.validated_data

    def test_fac_serializer_maps_incoming_id_field_to_fac_id_model_field(self):
        data = {
            "id": "FAC-SPEC-ID-001",
            "authorization_reference": "AUTH001",
            "total_costs": {"excl_vat": 5.00},
            "currency": "EUR",
            "eft_data": ["EFT_DATA_1"],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationSerializer(data=data)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["fac_id"] == "FAC-SPEC-ID-001"

    def test_fac_serializer_accepts_incoming_total_costs_without_incl_vat(self):
        data = {
            "id": "FAC002",
            "authorization_reference": "AUTH002",
            "total_costs": {"excl_vat": 30.00},
            "currency": "NOK",
            "eft_data": ["EFT_DATA_2"],
            "capture_status_code": "FAILED",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationSerializer(data=data)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["total_cost_excl_vat"] == 30.00
        assert serializer.validated_data["total_cost_incl_vat"] is None
        assert serializer.validated_data["currency"] == "NOK"

    def test_fac_serializer_rejects_incoming_data_when_total_costs_missing(self):
        data = {
            "id": "FAC003",
            "authorization_reference": "AUTH003",
            "currency": "EUR",
            "eft_data": [],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationSerializer(data=data)

        assert not serializer.is_valid()
        assert "total_costs" in serializer.errors

    def test_fac_serializer_rejects_incoming_total_costs_when_excl_vat_is_invalid(
        self,
    ):
        data = {
            "id": "FAC004",
            "authorization_reference": "AUTH004",
            "total_costs": {"excl_vat": "not-a-number"},
            "currency": "EUR",
            "eft_data": [],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationSerializer(data=data)

        assert not serializer.is_valid()
        assert "total_costs" in serializer.errors
        assert "excl_vat" in serializer.errors["total_costs"]

    def test_fac_serializer_rejects_incoming_data_when_currency_missing(self):
        data = {
            "id": "FAC005",
            "authorization_reference": "AUTH005",
            "total_costs": {"excl_vat": 10.00},
            "eft_data": [],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationSerializer(data=data)

        assert not serializer.is_valid()
        assert "currency" in serializer.errors

    @pytest.mark.parametrize(
        "capture_status_code", ["SUCCESS", "PARTIAL_SUCCESS", "FAILED"]
    )
    def test_fac_serializer_accepts_all_valid_capture_status_codes(
        self, capture_status_code
    ):
        data = {
            "id": f"FAC-{capture_status_code}",
            "authorization_reference": "AUTH-STATUS",
            "total_costs": {"excl_vat": 0.00},
            "currency": "EUR",
            "eft_data": ["EFT_ITEM"],
            "capture_status_code": capture_status_code,
            "last_updated": timezone.now().isoformat(),
        }

        serializer = FinancialAdviceConfirmationSerializer(data=data)

        assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
class TestFACSerializerOutgoing:
    def test_fac_serializer_returns_outgoing_id_field_not_fac_id(self, db_fac):
        fac = db_fac(
            fac_id="FAC010",
            authorization_reference="AUTH010",
            total_cost_excl_vat=10.50,
            total_cost_incl_vat=12.60,
            currency="EUR",
            eft_data=["DATA"],
            capture_status_code="SUCCESS",
            last_updated=timezone.now(),
        )

        data = FinancialAdviceConfirmationSerializer(fac).data

        assert "id" in data
        assert data["id"] == "FAC010"
        assert "fac_id" not in data

    def test_fac_serializer_returns_outgoing_total_costs_as_spec_nested_object(
        self, db_fac
    ):
        fac = db_fac(
            fac_id="FAC011",
            authorization_reference="AUTH011",
            total_cost_excl_vat=10.50,
            total_cost_incl_vat=12.60,
            currency="EUR",
            eft_data=["DATA"],
            capture_status_code="SUCCESS",
            last_updated=timezone.now(),
        )

        data = FinancialAdviceConfirmationSerializer(fac).data

        assert "total_costs" in data
        assert data["total_costs"]["excl_vat"] == 10.50
        assert data["total_costs"]["incl_vat"] == 12.60

    def test_fac_serializer_returns_outgoing_currency_at_root_level_not_inside_total_costs(
        self, db_fac
    ):
        fac = db_fac(
            fac_id="FAC012",
            authorization_reference="AUTH012",
            total_cost_excl_vat=20.00,
            total_cost_incl_vat=None,
            currency="USD",
            eft_data=["DATA"],
            capture_status_code="SUCCESS",
            last_updated=timezone.now(),
        )

        data = FinancialAdviceConfirmationSerializer(fac).data

        assert "currency" in data
        assert data["currency"] == "USD"
        assert "currency" not in data["total_costs"]

    def test_fac_serializer_omits_incl_vat_from_outgoing_total_costs_when_null(
        self, db_fac
    ):
        fac = db_fac(
            fac_id="FAC013",
            authorization_reference="AUTH013",
            total_cost_excl_vat=50.00,
            total_cost_incl_vat=None,
            currency="USD",
            eft_data=["DATA"],
            capture_status_code="SUCCESS",
            last_updated=timezone.now(),
        )

        data = FinancialAdviceConfirmationSerializer(fac).data

        assert "total_costs" in data
        assert data["total_costs"]["excl_vat"] == 50.00
        assert "incl_vat" not in data["total_costs"]


@pytest.mark.django_db
class TestFACSerializerRoundtrip:
    def test_fac_serializer_roundtrip_preserves_total_costs_and_currency_through_nested_to_flat_to_nested(
        self, db_fac
    ):
        incoming_data = {
            "id": "FAC_RT001",
            "authorization_reference": "AUTH_RT001",
            "total_costs": {"excl_vat": 45.50, "incl_vat": 56.65},
            "currency": "EUR",
            "eft_data": ["DATA1", "DATA2"],
            "capture_status_code": "SUCCESS",
            "last_updated": timezone.now().isoformat(),
        }

        write_serializer = FinancialAdviceConfirmationSerializer(data=incoming_data)
        assert write_serializer.is_valid(), write_serializer.errors

        fac = db_fac(**write_serializer.validated_data)
        outgoing_data = FinancialAdviceConfirmationSerializer(fac).data

        assert outgoing_data["id"] == "FAC_RT001"
        assert outgoing_data["total_costs"]["excl_vat"] == 45.50
        assert outgoing_data["total_costs"]["incl_vat"] == 56.65
        assert outgoing_data["currency"] == "EUR"
        assert "fac_id" not in outgoing_data
        assert "currency" not in outgoing_data["total_costs"]
