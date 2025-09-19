from unittest.mock import MagicMock, patch

import pytest

from ocpi22.commands.services import StartCommandService


class TestCommandServices:
    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_includes_all_required_fields(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        validated_data = {
            "token": {
                "uid": "TOKEN123",
                "country_code": "NL",
                "party_id": "TST",
                "type": "RFID",
                "contract_id": "CONTRACT123",
            },
            "authorization_reference": "AUTH123",
            "evse_uid": "EVSE001",
            "connector_id": "CONN001",
            "location_id": "LOC001",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        assert (
            payload["response_url"]
            == "http://testserver.test/commands/results/AUTH123/"
        )
        assert payload["token"]["uid"] == "TOKEN123"
        assert payload["token"]["type"] == "RFID"
        assert payload["authorization_reference"] == "AUTH123"
        assert payload["evse_uid"] == "EVSE001"
        assert payload["connector_id"] == "CONN001"
        assert payload["billed_to"] == "NL*TST"

    @patch("ocpi22.commands.services.generate_random_token")
    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_generates_auth_reference_when_missing(
        self, mock_build_uri, mock_generate_token
    ):
        mock_generate_token.return_value = "GENERATED_AUTH_456"
        mock_build_uri.return_value = (
            "http://testserver.test/commands/results/GENERATED_AUTH_456/"
        )

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "",
            "evse_uid": "EVSE001",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        mock_generate_token.assert_called_once()
        assert payload["authorization_reference"] == "GENERATED_AUTH_456"
        assert "GENERATED_AUTH_456" in payload["response_url"]

    @patch("ocpi22.commands.services.generate_random_token")
    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_generates_auth_reference_when_none(
        self, mock_build_uri, mock_generate_token
    ):
        mock_generate_token.return_value = "GENERATED_AUTH_789"
        mock_build_uri.return_value = (
            "http://testserver.test/commands/results/GENERATED_AUTH_789/"
        )

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": None,
            "evse_uid": "EVSE001",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        mock_generate_token.assert_called_once()
        assert payload["authorization_reference"] == "GENERATED_AUTH_789"

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_preserves_existing_auth_reference(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = (
            "http://testserver.test/commands/results/EXISTING_AUTH/"
        )

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "EXISTING_AUTH",
            "evse_uid": "EVSE001",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        assert payload["authorization_reference"] == "EXISTING_AUTH"

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_converts_token_type_to_string(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        # Token type might come in as an enum or other object
        token_type_enum = MagicMock()
        token_type_enum.__str__ = MagicMock(return_value="RFID")

        validated_data = {
            "token": {"uid": "TOKEN123", "type": token_type_enum},
            "authorization_reference": "AUTH123",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        assert payload["token"]["type"] == "RFID"
        assert isinstance(payload["token"]["type"], str)

    @pytest.mark.parametrize(
        "token_uid,expected_uid",
        [
            ("TOKEN123", "TOKEN123"),
            ("DUPLICATE_TOKEN_456", "DUPLICATE_TOKEN_456"),
            ("RFID*789*ABC", "RFID*789*ABC"),
            ("TOKEN_WITH_SPECIAL@CHARS", "TOKEN_WITH_SPECIAL@CHARS"),
        ],
    )
    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_preserves_token_uid_for_duplicated_tokens(
        self, mock_build_uri, token_uid, expected_uid
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        validated_data = {
            "token": {"uid": token_uid, "type": "RFID"},
            "authorization_reference": "AUTH123",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        assert payload["token"]["uid"] == expected_uid

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_handles_none_billed_to(self, mock_build_uri):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "AUTH123",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(None, validated_data)

        assert "billed_to" not in payload
        assert payload["token"]["uid"] == "TOKEN123"

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_maps_connector_id_correctly(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "AUTH123",
            "connector_id": "CONNECTOR_FROM_REQUEST",
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        assert payload["connector_id"] == "CONNECTOR_FROM_REQUEST"

    @pytest.mark.parametrize(
        "evse_uid,connector_id",
        [
            ("EVSE001", "CONN001"),
            ("", ""),
            (None, None),
        ],
    )
    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_handles_optional_fields(
        self, mock_build_uri, evse_uid, connector_id
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        billed_to = MagicMock()
        billed_to.get_party.return_value = "NL*TST"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "AUTH123",
            "evse_uid": evse_uid,
            "connector_id": connector_id,
        }

        service = StartCommandService()
        payload = service._prepare_start_session_payload(billed_to, validated_data)

        assert payload["evse_uid"] == evse_uid
        assert payload["connector_id"] == connector_id
