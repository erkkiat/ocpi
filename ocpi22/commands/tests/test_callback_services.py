import json
import uuid
from unittest.mock import Mock, patch

import pytest
import requests
import responses
from requests.exceptions import Timeout, ConnectionError, RequestException

from ocpi22.commands.serializers import CommandResultType
from ocpi22.commands.services import CallBackService, CallbackResult
from ocpi22.commands.models import CallBacks, CallBackExecutionStatus
from ocpi22.commands.repository import CallBackRepository
from ocpi22.models.session import Session
from ocpi22.tests.factories import (
    CredentialsFactory,
    CredentialsRoleFactory,
    BusinessDetailsFactory,
    OCPISessionFactory,
    CdrTokenFactory,
)
from ocpiconnector.party import Party
from webhooks.choices import RemoteCommandType


@pytest.fixture
def callback_instance(db):
    credentials = CredentialsFactory()
    emsp_business_details = BusinessDetailsFactory(name="Test EMSP")
    emsp_credentials_role = CredentialsRoleFactory(
        role="EMSP",
        country_code="NL",
        party_id="TST",
        business_details=emsp_business_details,
        credentials=credentials,
    )

    cdr_token = CdrTokenFactory(
        uid=str(uuid.uuid4()), ocpi_master=emsp_credentials_role
    )
    session = OCPISessionFactory(
        cdr_token=cdr_token,
        billed_to=emsp_credentials_role,
        ocpi_master=emsp_credentials_role,
        credentials=credentials,
        authorization_reference=str(uuid.uuid4()),
        status=Session.PENDING,
    )

    callback = CallBacks.objects.create(
        session=session,
        callback_url="https://example.com/callback",
        authorization_reference=session.authorization_reference,
        execution_status=CallBackExecutionStatus.PENDING,
    )

    return callback


@pytest.fixture
def callback_without_session(db):
    callback = CallBacks.objects.create(
        session=None,
        callback_url="https://example.com/callback",
        authorization_reference=str(uuid.uuid4()),
        execution_status=CallBackExecutionStatus.PENDING,
    )
    return callback


@pytest.fixture
def callback_without_credentials(db):
    session = OCPISessionFactory(
        credentials=None,
        status=Session.PENDING,
    )

    callback = CallBacks.objects.create(
        session=session,
        callback_url="https://example.com/callback",
        authorization_reference=session.authorization_reference,
        execution_status=CallBackExecutionStatus.PENDING,
    )
    return callback


@pytest.fixture
def mock_request_session():
    mock_session = Mock(spec=requests.Session)
    return mock_session


@pytest.mark.django_db
class TestCallbackService:
    def test_mark_success_updates_callback_status_and_response_fields(
        self, callback_instance
    ):
        response_status_code = 200
        response_body = "Success response"

        CallBackService.mark_success(
            callback_instance, response_status_code, response_body
        )

        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.SUCCESS
        assert callback_instance.response_status_code == response_status_code
        assert callback_instance.response_body == response_body
        assert callback_instance.executed_at is not None

    def test_mark_success_without_optional_fields_updates_status_only(
        self, callback_instance
    ):
        CallBackService.mark_success(callback_instance)

        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.SUCCESS
        assert callback_instance.response_status_code is None
        assert callback_instance.response_body is None
        assert callback_instance.executed_at is not None

    def test_mark_failed_updates_callback_status_and_response_fields(
        self, callback_instance
    ):
        response_status_code = 500
        response_body = "Error response"

        CallBackService.mark_failed(
            callback_instance, response_status_code, response_body
        )

        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.FAILED
        assert callback_instance.response_status_code == response_status_code
        assert callback_instance.response_body == response_body
        assert callback_instance.executed_at is not None

    def test_mark_failed_without_optional_fields_updates_status_only(
        self, callback_instance
    ):
        CallBackService.mark_failed(callback_instance)

        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.FAILED
        assert callback_instance.response_status_code is None
        assert callback_instance.response_body is None
        assert callback_instance.executed_at is not None

    def test_create_callback_creates_new_callback_with_correct_fields(
        self, callback_instance
    ):
        session = callback_instance.session
        callback_url = "https://newcallback.com/test"
        auth_reference = str(uuid.uuid4())

        new_callback = CallBackService.create_callback(
            session, callback_url, auth_reference
        )

        assert new_callback.session == session
        assert new_callback.callback_url == callback_url
        assert new_callback.authorization_reference == auth_reference
        assert new_callback.execution_status == CallBackExecutionStatus.PENDING

    def test_create_command_result_payload_with_accepted_result_returns_empty_message_list(
        self,
    ):
        payload = CallBackService.create_command_result_payload(
            CommandResultType.ACCEPTED, None
        )

        assert payload["result"] == "ACCEPTED"
        assert payload["message"] == []

    def test_create_command_result_payload_with_accepted_result_and_custom_message_returns_empty_message_list(
        self,
    ):
        payload = CallBackService.create_command_result_payload(
            CommandResultType.ACCEPTED, "Custom message"
        )

        assert payload["result"] == "ACCEPTED"
        assert payload["message"] == []

    def test_create_command_result_payload_with_rejected_result_and_no_message_returns_default_message(
        self,
    ):
        payload = CallBackService.create_command_result_payload(
            CommandResultType.REJECTED, None
        )

        assert payload["result"] == "REJECTED"
        assert "message" in payload
        assert isinstance(payload["message"], list)
        assert len(payload["message"]) > 0

    def test_create_command_result_payload_with_rejected_result_and_custom_message_returns_custom_message(
        self,
    ):
        custom_message = "Custom rejection message"
        payload = CallBackService.create_command_result_payload(
            CommandResultType.REJECTED, custom_message
        )

        assert payload["result"] == "REJECTED"
        assert payload["message"] == [{"language": "en", "text": custom_message}]

    @pytest.mark.parametrize(
        "command_result",
        [
            CommandResultType.FAILED,
            CommandResultType.TIMEOUT,
            CommandResultType.NOT_SUPPORTED,
        ],
    )
    def test_create_command_result_payload_with_other_results_returns_messagetext_or_default(
        self, command_result
    ):
        payload = CallBackService.create_command_result_payload(command_result, None)

        assert payload["result"] == command_result.value.upper()
        assert "message" in payload
        assert isinstance(payload["message"], list)

    def test_execute_callback_request_with_empty_callback_url_returns_failure(
        self, mock_request_session
    ):
        result = CallBackService.execute_callback_request(
            callback_url="",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=mock_request_session,
        )

        assert result.success is False
        assert result.error_message == "Empty callback URL"

    def test_execute_callback_request_with_empty_auth_token_returns_failure(
        self, mock_request_session
    ):
        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="",
            request=mock_request_session,
        )

        assert result.success is False
        assert result.error_message == "Empty auth token"

    @pytest.mark.parametrize("status_code", [200, 201, 202])
    @responses.activate
    def test_execute_callback_request_with_success_status_returns_success(
        self, status_code
    ):
        responses.add(
            responses.POST,
            "https://example.com/callback",
            body="Success response",
            status=status_code,
        )

        session = requests.Session()
        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=session,
        )

        assert result.success is True
        assert result.status_code == status_code
        assert result.response_body == "Success response"

    @pytest.mark.parametrize("status_code", [400, 404, 500])
    @responses.activate
    def test_execute_callback_request_with_error_status_returns_failure(
        self, status_code
    ):
        responses.add(
            responses.POST,
            "https://example.com/callback",
            body="Error response",
            status=status_code,
        )

        session = requests.Session()
        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=session,
        )

        assert result.success is False
        assert result.status_code == status_code
        assert result.response_body == "Error response"
        assert result.error_message == f"HTTP {status_code}"

    def test_execute_callback_request_with_timeout_returns_failure(
        self, mock_request_session
    ):
        mock_request_session.post.side_effect = Timeout()

        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=mock_request_session,
        )

        assert result.success is False
        assert (
            result.error_message
            == f"Request timeout after {CallBackService.REQUEST_TIMEOUT} seconds"
        )

    def test_execute_callback_request_with_connection_error_returns_failure(
        self, mock_request_session
    ):
        mock_request_session.post.side_effect = ConnectionError()

        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=mock_request_session,
        )

        assert result.success is False
        assert result.error_message == "Connection error"

    def test_execute_callback_request_with_request_exception_returns_failure(
        self, mock_request_session
    ):
        mock_request_session.post.side_effect = RequestException()

        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=mock_request_session,
        )

        assert result.success is False
        assert result.error_message == "Request error"

    def test_execute_callback_request_with_unexpected_exception_returns_failure(
        self, mock_request_session
    ):
        mock_request_session.post.side_effect = ValueError("Unexpected error")

        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=mock_request_session,
        )

        assert result.success is False
        assert result.error_message == "Unexpected error"

    @responses.activate
    def test_execute_callback_request_uses_correct_headers_and_timeout(self):
        responses.add(
            responses.POST, "https://example.com/callback", body="Success", status=200
        )

        to_party = Party("NL", "TST")
        sender_party = Party("NL", "CPO")

        session = requests.Session()
        result = CallBackService.execute_callback_request(
            callback_url="https://example.com/callback",
            payload={"result": "ACCEPTED"},
            auth_token="test_token",
            request=session,
            to_party=to_party,
            sender_party=sender_party,
        )

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.url == "https://example.com/callback"
        request_body = json.loads(request.body)
        assert request_body == {"result": "ACCEPTED"}
        assert "Authorization" in request.headers
        assert result.success is True

    def test_execute_callback_with_missing_session_marks_callback_failed(
        self, callback_without_session
    ):
        result = CallBackService.execute_callback(
            callback_without_session, CommandResultType.ACCEPTED
        )

        assert result is False
        callback_without_session.refresh_from_db()
        assert (
            callback_without_session.execution_status == CallBackExecutionStatus.FAILED
        )
        assert callback_without_session.response_body == "Missing session"

    def test_execute_callback_with_missing_credentials_marks_callback_failed(
        self, callback_without_credentials
    ):
        result = CallBackService.execute_callback(
            callback_without_credentials, CommandResultType.ACCEPTED
        )

        assert result is False
        callback_without_credentials.refresh_from_db()
        assert (
            callback_without_credentials.execution_status
            == CallBackExecutionStatus.FAILED
        )
        assert callback_without_credentials.response_body == "Missing credentials"

    def test_execute_callback_with_missing_theirs_token_marks_callback_failed(self):
        credentials = CredentialsFactory(theirs="dummy_token")
        emsp_business_details = BusinessDetailsFactory(name="Test EMSP")
        emsp_credentials_role = CredentialsRoleFactory(
            role="EMSP",
            country_code="NL",
            party_id="TST",
            business_details=emsp_business_details,
            credentials=credentials,
        )

        cdr_token = CdrTokenFactory(
            uid=str(uuid.uuid4()), ocpi_master=emsp_credentials_role
        )
        session = OCPISessionFactory(
            cdr_token=cdr_token,
            billed_to=emsp_credentials_role,
            ocpi_master=emsp_credentials_role,
            credentials=credentials,
            authorization_reference=str(uuid.uuid4()),
            status=Session.PENDING,
        )

        callback = CallBacks.objects.create(
            session=session,
            callback_url="https://example.com/callback",
            authorization_reference=session.authorization_reference,
            execution_status=CallBackExecutionStatus.PENDING,
        )

        with patch.object(credentials, "theirs", None):
            result = CallBackService.execute_callback(
                callback, CommandResultType.ACCEPTED
            )

        assert result is False
        callback.refresh_from_db()
        assert callback.execution_status == CallBackExecutionStatus.FAILED
        assert callback.response_body == "Missing credentials token"

    @patch("ocpi22.commands.services.get_our_party")
    def test_execute_callback_with_get_sender_party_exception_marks_callback_failed(
        self, mock_get_our_party, callback_instance
    ):
        mock_get_our_party.side_effect = ValueError("Unable to determine sender party")

        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.ACCEPTED
        )

        assert result is False
        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.FAILED
        assert (
            callback_instance.response_body
            == "Failed to get sender party: Unable to determine sender party"
        )

    def test_execute_callback_with_get_recipient_party_exception_marks_callback_failed(
        self, callback_instance
    ):
        with patch.object(
            callback_instance.session.ocpi_master,
            "get_party",
            side_effect=AttributeError("Missing party info"),
        ):
            result = CallBackService.execute_callback(
                callback_instance, CommandResultType.ACCEPTED
            )

        assert result is False
        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.FAILED
        assert (
            callback_instance.response_body
            == "Failed to get recipient party: Missing party info"
        )

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    @responses.activate
    def test_execute_callback_with_successful_request_marks_callback_success(
        self, mock_get_cert_request, callback_instance
    ):
        responses.add(
            responses.POST,
            "https://example.com/callback",
            json={"status": "success"},
            status=200,
        )

        mock_session = requests.Session()
        mock_get_cert_request.return_value = mock_session

        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.ACCEPTED, "Test message"
        )

        assert result is True
        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.SUCCESS
        assert callback_instance.response_status_code == 200

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    @responses.activate
    def test_execute_callback_with_failed_request_marks_callback_failed(
        self, mock_get_cert_request, callback_instance
    ):
        responses.add(
            responses.POST,
            "https://example.com/callback",
            json={"error": "Server error"},
            status=500,
        )

        mock_session = requests.Session()
        mock_get_cert_request.return_value = mock_session

        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.ACCEPTED
        )

        assert result is False
        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.FAILED
        assert callback_instance.response_status_code == 500
        assert callback_instance.response_body == "HTTP 500"

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    def test_execute_callback_with_timeout_exception_marks_callback_failed(
        self, mock_get_cert_request, callback_instance
    ):
        mock_session = Mock(spec=requests.Session)
        mock_session.post.side_effect = Timeout()
        mock_get_cert_request.return_value = mock_session

        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.ACCEPTED
        )

        assert result is False
        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.FAILED
        assert (
            f"Request timeout after {CallBackService.REQUEST_TIMEOUT} seconds"
            in callback_instance.response_body
        )

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    def test_execute_callback_with_unexpected_exception_marks_callback_failed(
        self, mock_get_cert_request, callback_instance
    ):
        mock_get_cert_request.side_effect = ValueError("Unexpected error")

        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.ACCEPTED
        )

        assert result is False
        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.FAILED
        assert "Unexpected error: Unexpected error" in callback_instance.response_body

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    @responses.activate
    def test_execute_callback_with_accepted_result_sends_empty_message_list(
        self, mock_get_cert_request, callback_instance
    ):
        responses.add(
            responses.POST,
            "https://example.com/callback",
            json={"status": "success"},
            status=200,
        )

        mock_session = requests.Session()
        mock_get_cert_request.return_value = mock_session

        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.ACCEPTED, "Test message"
        )

        assert result is True
        callback_instance.refresh_from_db()
        assert callback_instance.execution_status == CallBackExecutionStatus.SUCCESS

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["result"] == "ACCEPTED"
        assert request_body["message"] == []

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    @responses.activate
    def test_execute_callback_with_rejected_result_and_custom_message_sends_custom_message(
        self, mock_get_cert_request, callback_instance
    ):
        responses.add(
            responses.POST,
            "https://example.com/callback",
            json={"status": "success"},
            status=200,
        )

        mock_session = requests.Session()
        mock_get_cert_request.return_value = mock_session

        custom_message = "Custom rejection reason"
        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.REJECTED, custom_message
        )

        assert result is True

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["result"] == "REJECTED"
        assert request_body["message"] == [{"language": "en", "text": custom_message}]

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    @responses.activate
    def test_execute_callback_with_rejected_result_and_no_message_sends_default_message(
        self, mock_get_cert_request, callback_instance
    ):
        responses.add(
            responses.POST,
            "https://example.com/callback",
            json={"status": "success"},
            status=200,
        )

        mock_session = requests.Session()
        mock_get_cert_request.return_value = mock_session

        result = CallBackService.execute_callback(
            callback_instance, CommandResultType.REJECTED, None
        )

        assert result is True

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["result"] == "REJECTED"
        assert "message" in request_body
        assert isinstance(request_body["message"], list)
        assert len(request_body["message"]) > 0

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    def test_execute_callback_uses_correct_auth_token(
        self, mock_get_cert_request, callback_instance
    ):
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://example.com/callback",
                json={"status": "success"},
                status=200,
            )

            mock_session = requests.Session()
            mock_get_cert_request.return_value = mock_session

            expected_auth_token = callback_instance.session.credentials.theirs_base64()

            CallBackService.execute_callback(
                callback_instance, CommandResultType.ACCEPTED
            )

            assert len(rsps.calls) == 1
            auth_header = rsps.calls[0].request.headers.get("Authorization")
            assert expected_auth_token in auth_header

    def test_callback_result_named_tuple_creation(self):
        result = CallbackResult(
            success=True, status_code=200, response_body="Success", error_message=""
        )

        assert result.success is True
        assert result.status_code == 200
        assert result.response_body == "Success"
        assert result.error_message == ""

    def test_callback_result_named_tuple_with_minimal_fields(self):
        result = CallbackResult(success=False)

        assert result.success is False
        assert result.status_code is None
        assert result.response_body is None
        assert result.error_message is None


class TestCallBackServiceSendCallback:
    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=Session)
        session.uid = "test-session-uid"
        session.id = 123
        return session

    @pytest.fixture
    def mock_callback_service(self):
        return CallBackService()

    @pytest.fixture
    def mock_callback(self):
        callback = Mock(spec=CallBacks)
        callback.id = 456
        callback.callback_url = "https://example.com/callback"
        return callback

    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    def test_send_callback_returns_early_when_no_callback_found(
        self,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_callback_service,
        mock_session,
    ):
        mock_find_by_session_uid.return_value = None

        result = mock_callback_service.send_callback(
            session=mock_session,
            callback_type=RemoteCommandType.START_SESSION,
            result=CommandResultType.ACCEPTED,
        )

        mock_find_by_session_uid.assert_called_once_with(mock_session.uid)
        mock_execute_callback.assert_not_called()
        assert result is None

    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    @patch("ocpi22.commands.services.logger")
    def test_send_callback_logs_success_message_after_execution(
        self,
        mock_logger,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_callback_service,
        mock_session,
        mock_callback,
    ):
        mock_find_by_session_uid.return_value = mock_callback
        mock_execute_callback.return_value = True

        mock_callback_service.send_callback(
            session=mock_session,
            callback_type=RemoteCommandType.START_SESSION,
            result=CommandResultType.ACCEPTED,
        )

        expected_log_message = f"START_SESSION callback for session {mock_session.id} executed successfully to {mock_callback.callback_url}"
        mock_logger.info.assert_called_once_with(expected_log_message)

    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    def test_send_callback_handles_stop_session_callback_type(
        self,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_callback_service,
        mock_session,
        mock_callback,
    ):
        mock_find_by_session_uid.return_value = mock_callback
        mock_execute_callback.return_value = True

        mock_callback_service.send_callback(
            session=mock_session,
            callback_type=RemoteCommandType.STOP_SESSION,
            result=CommandResultType.ACCEPTED,
            message="Stop session message",
        )

        mock_execute_callback.assert_called_once_with(
            mock_callback, CommandResultType.ACCEPTED, "Stop session message"
        )

    @pytest.mark.parametrize(
        "command_result",
        [
            CommandResultType.ACCEPTED,
            CommandResultType.REJECTED,
            CommandResultType.FAILED,
            CommandResultType.TIMEOUT,
            CommandResultType.NOT_SUPPORTED,
        ],
    )
    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    def test_send_callback_handles_different_command_results(
        self,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_callback_service,
        mock_session,
        mock_callback,
        command_result,
    ):
        mock_find_by_session_uid.return_value = mock_callback
        mock_execute_callback.return_value = True

        mock_callback_service.send_callback(
            session=mock_session,
            callback_type=RemoteCommandType.START_SESSION,
            result=command_result,
        )

        mock_execute_callback.assert_called_once_with(
            mock_callback, command_result, None
        )

    @pytest.mark.parametrize(
        "callback_type",
        [
            RemoteCommandType.START_SESSION,
            RemoteCommandType.STOP_SESSION,
            RemoteCommandType.RESERVE_NOW,
            RemoteCommandType.CANCEL_RESERVATION,
            RemoteCommandType.UNLOCK_CONNECTOR,
        ],
    )
    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    def test_send_callback_handles_different_callback_types(
        self,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_callback_service,
        mock_session,
        mock_callback,
        callback_type,
    ):
        mock_find_by_session_uid.return_value = mock_callback
        mock_execute_callback.return_value = True

        mock_callback_service.send_callback(
            session=mock_session,
            callback_type=callback_type,
            result=CommandResultType.ACCEPTED,
        )

        mock_execute_callback.assert_called_once_with(
            mock_callback, CommandResultType.ACCEPTED, None
        )

    @patch("ocpi22.commands.services.get_certificate_loaded_request")
    @responses.activate
    def test_send_callback_with_accepted_result_sends_empty_message_list(
        self, mock_get_cert_request, db
    ):
        credentials = CredentialsFactory()
        emsp_business_details = BusinessDetailsFactory(name="Test EMSP")
        emsp_credentials_role = CredentialsRoleFactory(
            role="EMSP",
            country_code="NL",
            party_id="TST",
            business_details=emsp_business_details,
            credentials=credentials,
        )

        cdr_token = CdrTokenFactory(
            uid=str(uuid.uuid4()), ocpi_master=emsp_credentials_role
        )
        session = OCPISessionFactory(
            cdr_token=cdr_token,
            billed_to=emsp_credentials_role,
            ocpi_master=emsp_credentials_role,
            credentials=credentials,
            authorization_reference=str(uuid.uuid4()),
            status=Session.PENDING,
        )

        callback = CallBacks.objects.create(
            session=session,
            callback_url="https://example.com/callback",
            authorization_reference=session.authorization_reference,
            execution_status=CallBackExecutionStatus.PENDING,
        )

        responses.add(
            responses.POST,
            "https://example.com/callback",
            json={"status": "success"},
            status=200,
        )

        mock_session = requests.Session()
        mock_get_cert_request.return_value = mock_session

        callback_service = CallBackService()

        result = callback_service.send_callback(
            session=session,
            callback_type=RemoteCommandType.START_SESSION,
            result=CommandResultType.ACCEPTED,
            message="Integration test message",
        )

        assert result is None

        callback.refresh_from_db()
        assert callback.execution_status == CallBackExecutionStatus.SUCCESS
        assert callback.response_status_code == 200
        assert callback.executed_at is not None

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["result"] == "ACCEPTED"
        assert request_body["message"] == []
