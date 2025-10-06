import json
import uuid
from unittest.mock import Mock, patch

import pytest
import requests
import responses

from ocpi22.commands.serializers import CommandResultType
from ocpi22.commands.services import CallBackService, send_callback
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


class TestCallBackServiceSendCallback:
    @pytest.fixture
    def mock_session(self):
        session = Mock(spec=Session)
        session.uid = "test-session-uid"
        session.id = 123
        return session

    @pytest.fixture
    def pending_callback(self):
        callback = Mock(spec=CallBacks)
        callback.id = 456
        callback.callback_url = "https://example.com/callback"
        callback.execution_status = CallBackExecutionStatus.PENDING
        return callback

    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    def test_send_callback_returns_early_when_no_callback_found(
        self,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_session,
    ):
        mock_find_by_session_uid.return_value = None

        send_callback(
            session_uid=mock_session.uid,
            result="ACCEPTED",
        )

        mock_find_by_session_uid.assert_called_once_with(session_uid=mock_session.uid)
        mock_execute_callback.assert_not_called()

    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    @patch("ocpi22.commands.services.logger")
    def test_send_callback_logs_success_message_after_execution(
        self,
        mock_logger,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_session,
        pending_callback,
    ):
        mock_find_by_session_uid.return_value = pending_callback
        mock_execute_callback.return_value = True

        send_callback(
            session_uid=mock_session.uid,
            result="ACCEPTED",
        )

        expected_log_message = (
            f"Callback executed for COMMAND session {mock_session.uid} "
            f"to {pending_callback.callback_url}"
        )
        mock_logger.info.assert_called_once_with(expected_log_message)

    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    def test_send_callback_handles_stop_session_callback_type(
        self,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_session,
        pending_callback,
    ):
        mock_find_by_session_uid.return_value = pending_callback
        mock_execute_callback.return_value = True

        send_callback(
            session_uid=mock_session.uid,
            result="ACCEPTED",
            message="Stop session message",
        )

        mock_execute_callback.assert_called_once_with(
            pending_callback, CommandResultType.ACCEPTED, "Stop session message"
        )

    @pytest.mark.parametrize(
        "command_result",
        [
            "ACCEPTED",
            "REJECTED",
            "FAILED",
            "TIMEOUT",
            "NOT_SUPPORTED",
        ],
    )
    @patch.object(CallBackRepository, "find_by_session_uid")
    @patch.object(CallBackService, "execute_callback")
    def test_send_callback_handles_different_command_results(
        self,
        mock_execute_callback,
        mock_find_by_session_uid,
        mock_session,
        pending_callback,
        command_result,
    ):
        mock_find_by_session_uid.return_value = pending_callback
        mock_execute_callback.return_value = True

        send_callback(
            session_uid=mock_session.uid,
            result=command_result,
        )

        mock_execute_callback.assert_called_once_with(
            pending_callback, CommandResultType(command_result), None
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
        mock_session,
        pending_callback,
        callback_type,
    ):
        mock_find_by_session_uid.return_value = pending_callback
        mock_execute_callback.return_value = True

        send_callback(
            session_uid=mock_session.uid,
            result="ACCEPTED",
        )

        mock_execute_callback.assert_called_once_with(
            pending_callback, CommandResultType.ACCEPTED, None
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

        mock_requests_session = requests.Session()
        mock_get_cert_request.return_value = mock_requests_session

        send_callback(
            session_uid=session.uid,
            result="ACCEPTED",
            message="Integration test message",
        )

        callback.refresh_from_db()
        assert callback.execution_status == CallBackExecutionStatus.SUCCESS
        assert callback.response_status_code == 200
        assert callback.executed_at is not None

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["result"] == "ACCEPTED"
        assert request_body["message"] == []
