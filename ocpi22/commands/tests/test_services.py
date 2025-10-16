from unittest.mock import patch, MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from ocpi22.commands.services import StartCommandService, StopCommandServices
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.session import Session
from ocpi22.tests.factories import (
    EvseFactory,
    ConnectorFactory,
    CredentialsFactory,
    LocationFactory,
    CredentialsRoleFactory,
    OCPISessionFactory,
)
from ocpiconnector.party import Party
from webhooks.choices import RemoteCommandType


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
        CredentialsRoleFactory(
            country_code="NL", party_id="HUB", credentials=credentials
        )
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

    @patch("ocpi22.commands.services.build_absolute_uri")
    @pytest.mark.django_db
    @override_settings(HUBJECT_OPERATOR_ID="DE*ICE")
    def test_start_session_does_not_create_a_callback_for_hubject_sessions(
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

        CredentialsRoleFactory(
            country_code="DE", party_id="ICE", credentials=credentials
        )

        CredentialsRoleFactory(country_code="NL", party_id="MSP")

        with patch(
            "ocpi22.commands.services.StartCommandService.send_start_command_webhook"
        ) as mock_send_webhook:
            with patch(
                "ocpi22.commands.services.CallBackService.create_callback"
            ) as mock_create_callback:
                mock_send_webhook.return_value = {
                    "status_code": 1000,
                    "status_message": "Success",
                }
                StartCommandService().start_session(
                    sender_party=Party(country_code="NL", party_id="MSP"),
                    credentials=credentials,
                    validated_data=validated_data,
                )

        mock_create_callback.assert_not_called()


class TestStopCommandServices:
    @patch("ocpi22.commands.services.WebhookRepository.get_remote_command_webhook")
    def test_get_valid_webhook_with_active_webhook_returns_webhook(
        self, mock_get_webhook
    ):
        mock_webhook = MagicMock()
        mock_webhook.active = True
        mock_get_webhook.return_value = mock_webhook

        service = MagicMock()
        service.webhook_repo = MagicMock()
        service.webhook_repo.get_remote_command_webhook = mock_get_webhook

        from ocpi22.commands.services import StopCommandServices

        result = StopCommandServices().get_valid_webhook(RemoteCommandType.STOP_SESSION)
        assert result == mock_webhook

    @patch("ocpi22.commands.services.WebhookRepository.get_remote_command_webhook")
    def test_get_valid_webhook_with_no_webhook_raises_validation_error(
        self, mock_get_webhook
    ):
        mock_get_webhook.return_value = None

        from ocpi22.commands.services import StopCommandServices
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            StopCommandServices().get_valid_webhook(RemoteCommandType.STOP_SESSION)
        assert "No webhook configured" in str(exc_info.value)

    @patch("ocpi22.commands.services.WebhookRepository.get_remote_command_webhook")
    def test_get_valid_webhook_with_inactive_webhook_raises_validation_error(
        self, mock_get_webhook
    ):
        mock_webhook = MagicMock()
        mock_webhook.active = False
        mock_get_webhook.return_value = mock_webhook

        with pytest.raises(ValidationError) as exc_info:
            StopCommandServices().get_valid_webhook(RemoteCommandType.STOP_SESSION)
        assert "Inactive webhook found" in str(exc_info.value)

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.send_callback.delay")
    @patch("ocpi22.commands.services.StopCommandServices.send_stop_command_webhook")
    def test_stop_session_with_accepted_result_schedules_callback_task(
        self, mock_send_webhook, mock_send_callback
    ):
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory()
        evse = EvseFactory(location=location)
        connector = ConnectorFactory(evse=evse)
        credentials_role = CredentialsRoleFactory()
        session = OCPISessionFactory(
            uid="SESSION_123",
            status=Session.ACTIVE,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
        )

        validated_data = {
            "session_id": session.uid,
            "response_url": "https://example.com/callback",
        }

        StopCommandServices().stop_session(validated_data=validated_data)

        mock_send_callback.assert_called_once()

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.send_callback.delay")
    @patch("ocpi22.commands.services.StopCommandServices.send_stop_command_webhook")
    def test_stop_session_with_rejected_result_does_not_schedule_callback(
        self, mock_send_webhook, mock_send_callback
    ):
        mock_send_webhook.return_value = {"data": {"result": "REJECTED"}}

        location = LocationFactory()
        evse = EvseFactory(location=location)
        connector = ConnectorFactory(evse=evse)
        credentials_role = CredentialsRoleFactory()
        session = OCPISessionFactory(
            uid="SESSION_456",
            status=Session.ACTIVE,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
        )

        validated_data = {
            "session_id": session.uid,
            "response_url": "https://example.com/callback",
        }

        from ocpi22.commands.services import StopCommandServices

        StopCommandServices().stop_session(validated_data=validated_data)

        mock_send_callback.assert_not_called()

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StopCommandServices.send_stop_command_webhook")
    def test_stop_session_creates_callback_record(self, mock_send_webhook):
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory()
        evse = EvseFactory(location=location)
        connector = ConnectorFactory(evse=evse)
        credentials_role = CredentialsRoleFactory()
        session = OCPISessionFactory(
            uid="SESSION_789",
            status=Session.ACTIVE,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
        )

        validated_data = {
            "session_id": session.uid,
            "response_url": "https://example.com/callback",
        }

        from ocpi22.commands.services import StopCommandServices
        from ocpi22.commands.models import CallBacks

        StopCommandServices().stop_session(validated_data=validated_data)

        callback = CallBacks.objects.filter(session=session).first()
        assert callback is not None
        assert callback.callback_url == validated_data["response_url"]
