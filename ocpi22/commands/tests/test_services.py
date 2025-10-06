from unittest.mock import patch, MagicMock

import pytest

from ocpi22.commands.services import StartCommandService
from ocpi22.models.credentials import CredentialsRole
from ocpi22.tests.factories import (
    EvseFactory,
    ConnectorFactory,
    CredentialsFactory,
    LocationFactory,
)
from ocpiconnector.party import Party


class TestCommandServices:
    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_includes_all_required_fields(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        session = MagicMock()
        session.uid = "SESSION_UID_123"

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

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

        assert (
            payload["response_url"]
            == "http://testserver.test/commands/results/AUTH123/"
        )
        assert payload["token"]["uid"] == "TOKEN123"
        assert payload["token"]["type"] == "RFID"
        assert payload["authorization_reference"] == "AUTH123"
        assert payload["evse_uid"] == "EVSE001"
        assert payload["connector_id"] == "CONN001"
        assert payload["session_id"] == "SESSION_UID_123"

    @patch("ocpi22.commands.services.generate_random_token")
    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_generates_auth_reference_when_missing(
        self, mock_build_uri, mock_generate_token
    ):
        mock_generate_token.return_value = "GENERATED_AUTH_456"
        mock_build_uri.return_value = (
            "http://testserver.test/commands/results/GENERATED_AUTH_456/"
        )

        session = MagicMock()
        session.uid = "SESSION_UID_123"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "",
            "evse_uid": "EVSE001",
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

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

        session = MagicMock()
        session.uid = "SESSION_UID_123"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": None,
            "evse_uid": "EVSE001",
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

        mock_generate_token.assert_called_once()
        assert payload["authorization_reference"] == "GENERATED_AUTH_789"

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_preserves_existing_auth_reference(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = (
            "http://testserver.test/commands/results/EXISTING_AUTH/"
        )

        session = MagicMock()
        session.uid = "SESSION_UID_123"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "EXISTING_AUTH",
            "evse_uid": "EVSE001",
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

        assert payload["authorization_reference"] == "EXISTING_AUTH"

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_converts_token_type_to_string(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        session = MagicMock()
        session.uid = "SESSION_UID_123"

        token_type_enum = MagicMock()
        token_type_enum.__str__ = MagicMock(return_value="RFID")

        validated_data = {
            "token": {"uid": "TOKEN123", "type": token_type_enum},
            "authorization_reference": "AUTH123",
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

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

        session = MagicMock()
        session.uid = "SESSION_UID_123"

        validated_data = {
            "token": {"uid": token_uid, "type": "RFID"},
            "authorization_reference": "AUTH123",
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

        assert payload["token"]["uid"] == expected_uid

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_includes_session_id(self, mock_build_uri):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        session = MagicMock()
        session.uid = "UNIQUE_SESSION_ID_456"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "AUTH123",
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

        assert payload["session_id"] == "UNIQUE_SESSION_ID_456"

    @patch("ocpi22.commands.services.build_absolute_uri")
    def test_prepare_start_session_payload_maps_connector_id_correctly(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        session = MagicMock()
        session.uid = "SESSION_UID_123"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "AUTH123",
            "connector_id": "CONNECTOR_FROM_REQUEST",
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

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

        session = MagicMock()
        session.uid = "SESSION_UID_123"

        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "AUTH123",
            "evse_uid": evse_uid,
            "connector_id": connector_id,
        }

        payload = StartCommandService._prepare_start_session_payload(
            validated_data=validated_data,
            session=session,
        )

        assert payload["evse_uid"] == evse_uid
        assert payload["connector_id"] == connector_id

    @patch("ocpi22.commands.services.build_absolute_uri")
    @pytest.mark.django_db
    def test_start_session_creates_non_existing_msp_credentials_role(
        self, mock_build_uri
    ):
        mock_build_uri.return_value = "http://testserver.test/commands/results/AUTH123/"

        evse = EvseFactory(uid="EVSE001", location=LocationFactory())
        connector = ConnectorFactory(uid="CONN001", evse=evse)
        validated_data = {
            "token": {"uid": "TOKEN123", "type": "RFID"},
            "authorization_reference": "AUTH123",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": evse.location.uid,
            "response_url": "http://localhost/commands/results/AUTH123/",
        }
        credentials = CredentialsFactory()

        nl_cpo_cred_role = CredentialsRole.objects.filter(
            country_code="NL", party_id="CPO"
        ).first()
        assert nl_cpo_cred_role is None

        with patch(
            "ocpi22.commands.services.StartCommandService.send_start_command_webhook"
        ) as mock_send_webhook:
            mock_send_webhook.return_value = {
                "status_code": 1000,
                "status_message": "Success",
            }
            StartCommandService().start_session(
                sender_party=Party(country_code="NL", party_id="CPO"),
                credentials=credentials,
                validated_data=validated_data,
            )

        nl_cpo_cred_role = CredentialsRole.objects.filter(
            country_code="NL", party_id="CPO"
        ).first()
        assert nl_cpo_cred_role is not None
