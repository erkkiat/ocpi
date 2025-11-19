from unittest.mock import patch, MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from rest_framework import status

from ocpi22.commands.models import CallBacks
from ocpi22.commands.serializers import CommandResponseType
from ocpi22.commands.services import (
    StartCommandService,
    StopCommandServices,
    RemoteCommandServices,
)
from ocpi22.choices import MessageTexts
from ocpi22.exceptions import (
    EvseNotFoundError,
    LocationNotFoundError,
    EvseOccupiedError,
    ConnectorNotFoundError,
)
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi
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

        evse = EvseFactory(
            uid="EVSE001", location=LocationFactory(), status="AVAILABLE"
        )
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

        evse = EvseFactory(
            uid="EVSE001", location=LocationFactory(), status="AVAILABLE"
        )
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


class TestRemoteCommandServices:
    def test_create_ocpi_response_with_accepted_returns_ok_status_and_preparing_message(
        self,
    ):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(result=CommandResponseType.ACCEPTED)

        assert response.data["status_code"] == Ocpi.OK
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["result"] == CommandResponseType.ACCEPTED
        assert response.data["data"]["timeout"] == 60
        assert response.data["data"]["message"] == MessageTexts.get("ACCEPTED")

    def test_create_ocpi_response_with_rejected_returns_2000_status_and_default_error_message(
        self,
    ):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(result=CommandResponseType.REJECTED)

        assert response.data["status_code"] == 2000
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["result"] == CommandResponseType.REJECTED
        assert response.data["data"]["timeout"] == 60
        assert response.data["data"]["message"] == MessageTexts.get("REJECTED")

    def test_create_ocpi_response_with_rejected_and_custom_message_returns_custom_message(
        self,
    ):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(
            result=CommandResponseType.REJECTED, message="Charger is offline"
        )

        assert response.data["status_code"] == 2000
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["result"] == CommandResponseType.REJECTED
        assert response.data["data"]["timeout"] == 60
        assert response.data["data"]["message"] == [
            {"language": "en", "text": "Charger is offline"}
        ]

    def test_create_ocpi_response_with_not_supported_returns_2000_status_and_not_supported_message(
        self,
    ):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(
            result=CommandResponseType.NOT_SUPPORTED
        )

        assert response.data["status_code"] == 2000
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["result"] == CommandResponseType.NOT_SUPPORTED
        assert response.data["data"]["timeout"] == 60
        assert response.data["data"]["message"] == MessageTexts.get("NOT_SUPPORTED")

    def test_create_ocpi_response_with_unknown_session_returns_2000_status_and_default_error_message(
        self,
    ):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(
            result=CommandResponseType.UNKNOWN_SESSION
        )

        assert response.data["status_code"] == 2000
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["result"] == CommandResponseType.UNKNOWN_SESSION
        assert response.data["data"]["timeout"] == 60
        assert response.data["data"]["message"] == MessageTexts.get(
            "DEFAULT_CHARGER_ERROR_TEXT"
        )

    def test_create_ocpi_response_with_accepted_ignores_custom_message(self):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(
            result=CommandResponseType.ACCEPTED, message="This should be ignored"
        )

        assert response.data["data"]["message"] == MessageTexts.get("ACCEPTED")

    def test_create_ocpi_response_with_not_supported_ignores_custom_message(self):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(
            result=CommandResponseType.NOT_SUPPORTED, message="This should be ignored"
        )

        assert response.data["data"]["message"] == MessageTexts.get("NOT_SUPPORTED")

    @pytest.mark.parametrize(
        "result,expected_ocpi_status,expected_http_status,expected_message_key",
        [
            (
                CommandResponseType.ACCEPTED,
                Ocpi.OK,
                status.HTTP_200_OK,
                "ACCEPTED",
            ),
            (
                CommandResponseType.REJECTED,
                2000,
                status.HTTP_200_OK,
                "REJECTED",
            ),
            (
                CommandResponseType.NOT_SUPPORTED,
                2000,
                status.HTTP_200_OK,
                "NOT_SUPPORTED",
            ),
            (
                CommandResponseType.UNKNOWN_SESSION,
                2000,
                status.HTTP_200_OK,
                "DEFAULT_CHARGER_ERROR_TEXT",
            ),
        ],
    )
    def test_create_ocpi_response_maps_result_to_correct_status_and_message(
        self, result, expected_ocpi_status, expected_http_status, expected_message_key
    ):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(result=result)

        assert response.data["status_code"] == expected_ocpi_status
        assert response.status_code == expected_http_status
        assert response.data["data"]["result"] == result
        assert response.data["data"]["timeout"] == 60
        assert response.data["data"]["message"] == MessageTexts.get(
            expected_message_key
        )

    @patch("ocpi22.commands.services.CommandResponse")
    def test_create_ocpi_response_with_invalid_serializer_returns_500_error(
        self, mock_command_response
    ):
        mock_serializer_instance = MagicMock()
        mock_serializer_instance.is_valid.return_value = False
        mock_serializer_instance.errors = {"result": ["Invalid choice"]}
        mock_command_response.return_value = mock_serializer_instance

        service = RemoteCommandServices()

        response = service.create_ocpi_response(result=CommandResponseType.ACCEPTED)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data["status_code"] == Ocpi.OK
        assert response.data["status_message"] == "Internal error"
        assert response.data["data"] is None

    @pytest.mark.parametrize(
        "custom_message",
        [
            "EVSE is currently offline",
            "Vehicle not authorized",
            "Payment method declined",
            "Maximum concurrent sessions reached",
        ],
    )
    def test_create_ocpi_response_with_rejected_and_various_custom_messages_returns_exact_message(
        self, custom_message
    ):
        service = RemoteCommandServices()

        response = service.create_ocpi_response(
            result=CommandResponseType.REJECTED, message=custom_message
        )

        assert response.data["status_code"] == 2000
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["result"] == CommandResponseType.REJECTED
        assert response.data["data"]["timeout"] == 60
        assert response.data["data"]["message"] == [
            {"language": "en", "text": custom_message}
        ]


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

        result = StopCommandServices().get_valid_webhook(RemoteCommandType.STOP_SESSION)
        assert result == mock_webhook

    @patch("ocpi22.commands.services.WebhookRepository.get_remote_command_webhook")
    def test_get_valid_webhook_with_no_webhook_raises_validation_error(
        self, mock_get_webhook
    ):
        mock_get_webhook.return_value = None

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

        StopCommandServices().stop_session(validated_data=validated_data)

        callback = CallBacks.objects.filter(session=session).first()
        assert callback is not None
        assert callback.callback_url == validated_data["response_url"]

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StopCommandServices.send_stop_command_webhook")
    def test_stop_session_does_not_create_callback_record_when_route_through_oicp(
        self, mock_send_webhook, hubject_credentials
    ):
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory()
        evse = EvseFactory(location=location)
        connector = ConnectorFactory(evse=evse)
        credentials_role = hubject_credentials.roles.first()
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

        StopCommandServices().stop_session(validated_data=validated_data)

        callback = CallBacks.objects.filter(session=session).first()
        assert callback is None


class TestStartCommandServiceHelpers:
    @pytest.mark.django_db
    def test_get_evse_returns_evse_when_exists(self):
        location = LocationFactory()
        evse = EvseFactory(uid="EVSE123", location=location)
        service = StartCommandService()

        result = service._get_evse(evse_uid="EVSE123")

        assert result == evse
        assert result.uid == "EVSE123"

    @pytest.mark.django_db
    def test_get_evse_raises_evse_not_found_error_when_evse_does_not_exist(self):
        service = StartCommandService()

        with pytest.raises(EvseNotFoundError) as exc_info:
            service._get_evse(evse_uid="NONEXISTENT_EVSE")

        assert "EVSE not found for evse_uid NONEXISTENT_EVSE" in str(exc_info.value)

    @pytest.mark.django_db
    def test_get_location_returns_location_when_exists(self):
        location = LocationFactory(uid="LOC123")
        service = StartCommandService()

        result = service._get_location(location_uid="LOC123")

        assert result == location
        assert result.uid == "LOC123"

    @pytest.mark.django_db
    def test_get_location_raises_location_not_found_error_when_location_does_not_exist(
        self,
    ):
        service = StartCommandService()

        with pytest.raises(LocationNotFoundError) as exc_info:
            service._get_location(location_uid="NONEXISTENT_LOC")

        assert "Location not found for location_id NONEXISTENT_LOC" in str(
            exc_info.value
        )

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "evse_status",
        [
            Evse.OUTOFORDER,
            Evse.BLOCKED,
            Evse.INOPERATIVE,
            Evse.PLANNED,
            Evse.REMOVED,
            Evse.RESERVED,
            Evse.UNKNOWN,
            Evse.CHARGING,
        ],
    )
    def test_validate_evse_availability_raises_evse_occupied_error_when_evse_is_not_available(
        self, evse_status
    ):
        location = LocationFactory()
        evse = EvseFactory(uid="EVSE456", location=location, status=evse_status)
        service = StartCommandService()

        with pytest.raises(EvseOccupiedError) as exc_info:
            service._is_evse_available(evse)

        assert "Evse is not available for starting a session" in str(exc_info.value)

    @pytest.mark.django_db
    def test_validate_evse_availability_does_not_raise_error_for_available_statuses(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(uid="EVSE789", location=location, status=Evse.AVAILABLE)
        service = StartCommandService()

        service._is_evse_available(evse)

    @pytest.mark.django_db
    def test_get_connector_returns_connector_when_exists(self):
        location = LocationFactory()
        evse = EvseFactory(location=location)
        connector = ConnectorFactory(uid="CONN123", evse=evse)
        service = StartCommandService()

        result = service._get_connector(connector_uid="CONN123")

        assert result == connector
        assert result.uid == "CONN123"

    @pytest.mark.django_db
    def test_get_connector_raises_connector_not_found_error_when_connector_does_not_exist(
        self,
    ):
        service = StartCommandService()

        with pytest.raises(ConnectorNotFoundError) as exc_info:
            service._get_connector(connector_uid="NONEXISTENT_CONN")

        assert "Connector not found for connector_id NONEXISTENT_CONN" in str(
            exc_info.value
        )

    @pytest.mark.django_db
    def test_get_first_connector_if_missing_returns_provided_connector_when_connector_id_given(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(uid="EVSE123", location=location)
        _ = ConnectorFactory(uid="CONN001", evse=evse)
        connector2 = ConnectorFactory(uid="CONN002", evse=evse)
        service = StartCommandService()

        result = service._get_first_connector_if_missing(
            evse=evse, connector_id="CONN002"
        )

        assert result == connector2
        assert result.uid == "CONN002"

    @pytest.mark.django_db
    def test_get_first_connector_if_missing_returns_first_connector_when_connector_id_not_given(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(uid="EVSE456", location=location)
        connector1 = ConnectorFactory(uid="CONN001", evse=evse)
        _ = ConnectorFactory(uid="CONN002", evse=evse)
        service = StartCommandService()

        result = service._get_first_connector_if_missing(evse=evse, connector_id=None)

        assert result == connector1
        assert result.uid == "CONN001"

    @pytest.mark.django_db
    def test_get_first_connector_if_missing_raises_connector_not_found_error_when_evse_has_no_connectors(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(uid="EVSE_NO_CONN", location=location)
        service = StartCommandService()

        with pytest.raises(ConnectorNotFoundError) as exc_info:
            service._get_first_connector_if_missing(evse=evse, connector_id=None)

        assert "No connector found for evse_uid EVSE_NO_CONN" in str(exc_info.value)

    @pytest.mark.django_db
    def test_get_first_connector_if_missing_raises_connector_not_found_error_when_provided_connector_id_does_not_exist(
        self,
    ):
        location = LocationFactory()
        evse = EvseFactory(uid="EVSE789", location=location)
        ConnectorFactory(uid="CONN001", evse=evse)
        service = StartCommandService()

        with pytest.raises(ConnectorNotFoundError) as exc_info:
            service._get_first_connector_if_missing(
                evse=evse, connector_id="NONEXISTENT_CONN"
            )

        assert "Connector not found for connector_id NONEXISTENT_CONN" in str(
            exc_info.value
        )


class TestStartCommandServiceStartSession:
    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_creates_new_session_when_no_existing_session_found(
        self, mock_send_webhook
    ):
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory(uid="LOC123")
        evse = EvseFactory(uid="EVSE123", location=location, status=Evse.AVAILABLE)
        connector = ConnectorFactory(uid="CONN123", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN123",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT123",
            },
            "authorization_reference": "AUTH123",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.status_code == status.HTTP_200_OK
        session = Session.objects.filter(authorization_reference="AUTH123").first()
        assert session is not None
        assert session.connector.uid == connector.uid
        assert session.evse.uid == evse.uid
        assert session.location.uid == location.uid

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_picks_first_connector_when_connector_id_not_provided(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory(uid="LOC456")
        evse = EvseFactory(uid="EVSE456", location=location, status=Evse.AVAILABLE)
        connector1 = ConnectorFactory(uid="CONN_FIRST", evse=evse)
        _ = ConnectorFactory(uid="CONN_SECOND", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN456",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT456",
            },
            "authorization_reference": "AUTH456",
            "evse_uid": evse.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.status_code == status.HTTP_200_OK
        session = Session.objects.filter(authorization_reference="AUTH456").first()
        assert session is not None
        assert session.connector.uid == connector1.uid

    @pytest.mark.django_db
    def test_start_session_raises_location_not_found_error_when_location_does_not_exist(
        self,
    ):
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN789",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT789",
            },
            "authorization_reference": "AUTH789",
            "evse_uid": "EVSE789",
            "location_id": "NONEXISTENT_LOC",
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()

        with pytest.raises(LocationNotFoundError) as exc_info:
            service.start_session(
                sender_party=Party(country_code="FI", party_id="MSP"),
                credentials=credentials_role.credentials,
                validated_data=validated_data,
            )

        assert "Location not found for location_id NONEXISTENT_LOC" in str(
            exc_info.value
        )

    @pytest.mark.django_db
    def test_start_session_raises_evse_not_found_error_when_evse_does_not_exist(self):
        location = LocationFactory(uid="LOC111")
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN111",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT111",
            },
            "authorization_reference": "AUTH111",
            "evse_uid": "NONEXISTENT_EVSE",
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()

        with pytest.raises(EvseNotFoundError) as exc_info:
            service.start_session(
                sender_party=Party(country_code="FI", party_id="MSP"),
                credentials=credentials_role.credentials,
                validated_data=validated_data,
            )

        assert "EVSE not found for evse_uid NONEXISTENT_EVSE" in str(exc_info.value)

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_raises_evse_occupied_error_when_evse_is_not_available(
        self,
        mock_send_webhook,
    ):
        location = LocationFactory(uid="LOC222")
        evse = EvseFactory(uid="EVSE222", location=location, status=Evse.BLOCKED)
        ConnectorFactory(uid="CONN_SECOND", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN222",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT222",
            },
            "authorization_reference": "AUTH222",
            "evse_uid": evse.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()

        with pytest.raises(EvseOccupiedError) as exc_info:
            service.start_session(
                sender_party=Party(country_code="FI", party_id="MSP"),
                credentials=credentials_role.credentials,
                validated_data=validated_data,
            )

        assert "Evse is not available for starting a session" in str(exc_info.value)

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_raises_evse_occupied_error_when_evse_is_charging(
        self, mock_send_webhook
    ):
        location = LocationFactory(uid="LOC333")
        evse = EvseFactory(uid="EVSE333", location=location, status=Evse.CHARGING)
        ConnectorFactory(uid="CONN_THIRD", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN333",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT333",
            },
            "authorization_reference": "AUTH333",
            "evse_uid": evse.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()

        with pytest.raises(EvseOccupiedError) as exc_info:
            service.start_session(
                sender_party=Party(country_code="FI", party_id="MSP"),
                credentials=credentials_role.credentials,
                validated_data=validated_data,
            )

        assert "Evse is not available for starting a session" in str(exc_info.value)

    @pytest.mark.django_db
    def test_start_session_raises_connector_not_found_error_when_provided_connector_does_not_exist(
        self,
    ):
        location = LocationFactory(uid="LOC444")
        evse = EvseFactory(uid="EVSE444", location=location, status=Evse.AVAILABLE)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN444",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT444",
            },
            "authorization_reference": "AUTH444",
            "evse_uid": evse.uid,
            "connector_id": "NONEXISTENT_CONN",
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()

        with pytest.raises(ConnectorNotFoundError) as exc_info:
            service.start_session(
                sender_party=Party(country_code="FI", party_id="MSP"),
                credentials=credentials_role.credentials,
                validated_data=validated_data,
            )

        assert "Connector not found for connector_id NONEXISTENT_CONN" in str(
            exc_info.value
        )

    @pytest.mark.django_db
    def test_start_session_raises_connector_not_found_error_when_evse_has_no_connectors(
        self,
    ):
        location = LocationFactory(uid="LOC555")
        evse = EvseFactory(uid="EVSE555", location=location, status=Evse.AVAILABLE)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN555",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT555",
            },
            "authorization_reference": "AUTH555",
            "evse_uid": evse.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()

        with pytest.raises(ConnectorNotFoundError) as exc_info:
            service.start_session(
                sender_party=Party(country_code="FI", party_id="MSP"),
                credentials=credentials_role.credentials,
                validated_data=validated_data,
            )

        assert "No connector found for evse_uid EVSE555" in str(exc_info.value)

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_returns_bad_request_when_active_session_already_exists(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        location = LocationFactory(uid="LOC666")
        evse = EvseFactory(uid="EVSE666", location=location, status=Evse.AVAILABLE)
        connector = ConnectorFactory(uid="CONN666", evse=evse)
        credentials_role = CredentialsRoleFactory()

        existing_session = OCPISessionFactory(
            uid="SESSION_EXISTING",
            status=Session.ACTIVE,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
            authorization_reference="AUTH666",
        )

        validated_data = {
            "token": {
                "uid": existing_session.cdr_token.uid,
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT666",
            },
            "authorization_reference": "AUTH666",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot start - ACTIVE session" in response.data["status_message"]
        mock_send_webhook.assert_not_called()

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_retries_pending_session_when_pending_session_exists(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory(uid="LOC777")
        evse = EvseFactory(uid="EVSE777", location=location, status=Evse.BLOCKED)
        connector = ConnectorFactory(uid="CONN777", evse=evse)
        credentials_role = CredentialsRoleFactory()

        existing_session = OCPISessionFactory(
            uid="SESSION_PENDING",
            status=Session.PENDING,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
            authorization_reference="AUTH777",
        )

        validated_data = {
            "token": {
                "uid": existing_session.cdr_token.uid,
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT777",
            },
            "authorization_reference": "AUTH777",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.status_code == status.HTTP_200_OK
        mock_send_webhook.assert_called_once()

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_retries_reservation_session_when_reservation_session_exists(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory(uid="LOC888")
        evse = EvseFactory(uid="EVSE888", location=location, status=Evse.BLOCKED)
        connector = ConnectorFactory(uid="CONN888", evse=evse)
        credentials_role = CredentialsRoleFactory()

        existing_session = OCPISessionFactory(
            uid="SESSION_RESERVATION",
            status=Session.RESERVATION,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
            authorization_reference="AUTH888",
        )

        validated_data = {
            "token": {
                "uid": existing_session.cdr_token.uid,
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT888",
            },
            "authorization_reference": "AUTH888",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.status_code == status.HTTP_200_OK
        mock_send_webhook.assert_called_once()

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_returns_bad_request_when_completed_session_exists(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        location = LocationFactory(uid="LOC999")
        evse = EvseFactory(uid="EVSE999", location=location, status=Evse.BLOCKED)
        connector = ConnectorFactory(uid="CONN999", evse=evse)
        credentials_role = CredentialsRoleFactory()

        existing_session = OCPISessionFactory(
            uid="SESSION_COMPLETED",
            status=Session.COMPLETED,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
            authorization_reference="AUTH999",
        )

        validated_data = {
            "token": {
                "uid": existing_session.cdr_token.uid,
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT999",
            },
            "authorization_reference": "AUTH999",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            "Cannot start - COMPLETED/INVALID session"
            in response.data["status_message"]
        )
        mock_send_webhook.assert_not_called()

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_returns_bad_request_when_invalid_session_exists(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        location = LocationFactory(uid="LOC101")
        evse = EvseFactory(uid="EVSE101", location=location, status=Evse.BLOCKED)
        connector = ConnectorFactory(uid="CONN101", evse=evse)
        credentials_role = CredentialsRoleFactory()

        existing_session = OCPISessionFactory(
            uid="SESSION_INVALID",
            status=Session.INVALID,
            connector=connector,
            evse=evse,
            location=location,
            credentials=credentials_role.credentials,
            authorization_reference="AUTH101",
        )

        validated_data = {
            "token": {
                "uid": existing_session.cdr_token.uid,
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT101",
            },
            "authorization_reference": "AUTH101",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            "Cannot start - COMPLETED/INVALID session"
            in response.data["status_message"]
        )
        mock_send_webhook.assert_not_called()

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_returns_accepted_when_webhook_returns_accepted(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory(uid="LOC102")
        evse = EvseFactory(uid="EVSE102", location=location, status=Evse.AVAILABLE)
        connector = ConnectorFactory(uid="CONN102", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN102",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT102",
            },
            "authorization_reference": "AUTH102",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.data["data"]["result"] == CommandResponseType.ACCEPTED
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_returns_rejected_when_webhook_returns_rejected(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        mock_send_webhook.return_value = {"data": {"result": "REJECTED"}}

        location = LocationFactory(uid="LOC103")
        evse = EvseFactory(uid="EVSE103", location=location, status=Evse.AVAILABLE)
        connector = ConnectorFactory(uid="CONN103", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN103",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT103",
            },
            "authorization_reference": "AUTH103",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.data["data"]["result"] == CommandResponseType.REJECTED
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_defaults_to_rejected_when_webhook_returns_invalid_result(
        self, mock_send_webhook
    ):
        get_credentialsrole.cache_clear()
        mock_send_webhook.return_value = {"data": {"result": "INVALID_VALUE"}}

        location = LocationFactory(uid="LOC104")
        evse = EvseFactory(uid="EVSE104", location=location, status=Evse.AVAILABLE)
        connector = ConnectorFactory(uid="CONN104", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN104",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT104",
            },
            "authorization_reference": "AUTH104",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        response = service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        assert response.data["data"]["result"] == CommandResponseType.REJECTED
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    @patch("ocpi22.commands.services.CallBackService.create_callback")
    @patch("ocpi22.commands.services.StartCommandService.send_start_command_webhook")
    def test_start_session_creates_callback_for_non_hubject_sessions(
        self, mock_send_webhook, mock_create_callback
    ):
        get_credentialsrole.cache_clear()
        mock_send_webhook.return_value = {"data": {"result": "ACCEPTED"}}

        location = LocationFactory(uid="LOC105")
        evse = EvseFactory(uid="EVSE105", location=location, status=Evse.AVAILABLE)
        connector = ConnectorFactory(uid="CONN105", evse=evse)
        credentials_role = CredentialsRoleFactory()

        validated_data = {
            "token": {
                "uid": "TOKEN105",
                "type": "RFID",
                "country_code": "FI",
                "party_id": "CPO",
                "contract_id": "CONTRACT105",
            },
            "authorization_reference": "AUTH105",
            "evse_uid": evse.uid,
            "connector_id": connector.uid,
            "location_id": location.uid,
            "response_url": "https://example.com/callback",
        }

        service = StartCommandService()
        service.start_session(
            sender_party=Party(country_code="FI", party_id="MSP"),
            credentials=credentials_role.credentials,
            validated_data=validated_data,
        )

        mock_create_callback.assert_called_once()
