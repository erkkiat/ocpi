import base64
import json

import pytest
import responses
from rest_framework import status
from responses import matchers

from ocpi22.models.session import Session
from ocpi22.tests.factories import (
    CredentialsFactory,
    CredentialsRoleFactory,
    BusinessDetailsFactory,
    OCPISessionFactory,
    LocationFactory,
    EvseFactory,
    ConnectorFactory,
)
from webhooks.choices import RemoteCommandType, WebhookType
from webhooks.factories import WebhookFactory, WebhookWithAuthFactory


@pytest.fixture
def nl_tst_credentials_role(emsp_credentials):
    business_details = BusinessDetailsFactory(name="Test EMSP")

    return CredentialsRoleFactory(
        role="EMSP",
        country_code="NL",
        party_id="TST",
        business_details=business_details,
        credentials=emsp_credentials,
    )


@pytest.fixture
def emsp_credentials():
    credentials = CredentialsFactory()
    return credentials


@pytest.fixture
def cpo_credentials():
    """Create CPO credentials for testing"""
    credentials = CredentialsFactory()
    business_details = BusinessDetailsFactory(name="Test CPO")
    CredentialsRoleFactory(
        role="CPO",
        country_code="NL",
        party_id="CPO",
        business_details=business_details,
        credentials=credentials,
    )
    return credentials


@pytest.fixture
def ocpi_headers(emsp_credentials, nl_tst_credentials_role):
    return {
        "HTTP_AUTHORIZATION": f"Token {base64.b64encode(emsp_credentials.ours.encode()).decode()}",
        "HTTP_OCPI_FROM_COUNTRY_CODE": "NL",
        "HTTP_OCPI_FROM_PARTY_ID": "TST",
        "HTTP_OCPI_TO_COUNTRY_CODE": "NL",
        "HTTP_OCPI_TO_PARTY_ID": "CPO",
        "CONTENT_TYPE": "application/json",
    }


@pytest.fixture
def valid_start_session_data():
    return {
        "response_url": "https://example.com/callback",
        "token": {
            "uid": "TOKEN123",
            "country_code": "NL",
            "party_id": "TST",
            "type": "RFID",
            "contract_id": "CONTRACT12",
        },
        "location_id": "LOC001",
        "evse_uid": "EVSE001",
        "connector_id": "CONN001",
        "authorization_reference": "AUTH123",
    }


@pytest.fixture
def valid_stop_session_data():
    return {"response_url": "https://example.com/callback", "session_id": "SESSION123"}


@pytest.fixture
def active_start_webhook():
    """Create an active webhook for START_SESSION commands"""
    return WebhookWithAuthFactory(
        type=WebhookType.REMOTE_COMMAND,
        command_type=RemoteCommandType.START_SESSION,
        active=True,
        url="https://webhook.example.com/start",
    )


@pytest.fixture
def active_stop_webhook():
    """Create an active webhook for STOP_SESSION commands"""
    return WebhookWithAuthFactory(
        type=WebhookType.REMOTE_COMMAND,
        command_type=RemoteCommandType.STOP_SESSION,
        active=True,
        url="https://webhook.example.com/stop",
    )


@pytest.mark.django_db
class TestStartSessionAPI:
    def test_start_session_with_no_data_returns_bad_request(
        self, client, nl_tst_credentials_role, ocpi_headers
    ):
        client.credentials = nl_tst_credentials_role.credentials
        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION", data={}, format="json", **ocpi_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_session_with_invalid_data_returns_validation_errors(
        self, client, emsp_credentials, ocpi_headers
    ):
        invalid_data = {
            "response_url": "invalid-url",
            "token": {"uid": ""},
            "location_id": "",
        }

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=invalid_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_data = response.json()
        assert "Please check your request parameters" in response_data["status_message"]

    def test_start_session_with_missing_token_fields_returns_validation_errors(
        self, client, nl_tst_credentials_role, ocpi_headers, valid_start_session_data
    ):
        client.credentials = nl_tst_credentials_role.credentials
        data = valid_start_session_data.copy()
        del data["token"]["uid"]

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_session_with_missing_location_id_returns_validation_errors(
        self, client, nl_tst_credentials_role, ocpi_headers, valid_start_session_data
    ):
        client.credentials = nl_tst_credentials_role.credentials
        data = valid_start_session_data.copy()
        del data["location_id"]

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_session_without_auth_headers_returns_unauthorized(
        self, client, valid_start_session_data
    ):
        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_start_session_with_invalid_sender_party_returns_unauthorized(
        self, client, emsp_credentials, valid_start_session_data
    ):
        invalid_headers = {
            "HTTP_AUTHORIZATION": f"Token {base64.b64encode(emsp_credentials.ours.encode()).decode()}",
            "HTTP_OCPI_FROM_COUNTRY_CODE": "INVALID",
            "HTTP_OCPI_FROM_PARTY_ID": "X",
            "CONTENT_TYPE": "application/json",
        }

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **invalid_headers,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @responses.activate
    def test_start_session_with_valid_data_webhook_accepted_creates_session(
        self,
        client,
        nl_tst_credentials_role,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        responses.add(
            responses.POST,
            active_start_webhook.url,
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )

        location = LocationFactory(uid=valid_start_session_data["location_id"])
        evse = EvseFactory(uid=valid_start_session_data["evse_uid"], location=location)
        connector = ConnectorFactory(
            uid=valid_start_session_data["connector_id"], evse=evse
        )

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["status_code"] == 1000
        assert response_data["data"]["result"] == "ACCEPTED"

        session = Session.objects.filter(
            authorization_reference="AUTH123",
            cdr_token__uid=valid_start_session_data["token"]["uid"],
        ).first()

        assert session
        assert session.location == location
        assert session.evse == evse
        assert session.connector == connector
        assert len(responses.calls) == 1
        assert responses.calls[0].request.url == active_start_webhook.url

        webhook_payload = json.loads(responses.calls[0].request.body)
        assert webhook_payload["session_id"] == session.uid

    @responses.activate
    def test_start_session_with_valid_data_webhook_rejected_session_still_created(
        self,
        client,
        nl_tst_credentials_role,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        responses.add(
            responses.POST,
            active_start_webhook.url,
            json={"data": {"result": "REJECTED"}},
            status=200,
        )

        location = LocationFactory(uid=valid_start_session_data["location_id"])
        evse = EvseFactory(uid=valid_start_session_data["evse_uid"], location=location)
        _ = ConnectorFactory(
            uid=valid_start_session_data["connector_id"], evse=evse
        )

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["status_code"] == 2000
        assert response_data["data"]["result"] == "REJECTED"

        session = Session.objects.filter(
            authorization_reference="AUTH123",
            cdr_token__uid=valid_start_session_data["token"]["uid"],
        ).first()
        assert session
        assert len(responses.calls) == 1
        webhook_payload = json.loads(responses.calls[0].request.body)
        assert webhook_payload["session_id"] == session.uid

    def test_start_session_with_existing_active_session_returns_bad_request(
        self, client, nl_tst_credentials_role, ocpi_headers, valid_start_session_data
    ):
        client.credentials = nl_tst_credentials_role.credentials

        OCPISessionFactory(
            authorization_reference="AUTH123",
            status=Session.ACTIVE,
            billed_to=nl_tst_credentials_role,
            cdr_token__uid=valid_start_session_data["token"]["uid"],
        )

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_data = response.json()
        assert "Cannot start - ACTIVE session" in response_data["status_message"]

    @responses.activate
    def test_start_session_with_existing_pending_session_retries_webhook(
        self,
        client,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
        nl_tst_credentials_role,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        existing_session = OCPISessionFactory(
            authorization_reference="AUTH123",
            status=Session.PENDING,
            billed_to=nl_tst_credentials_role,
            cdr_token__uid=valid_start_session_data["token"]["uid"],
        )

        responses.add(
            responses.POST,
            active_start_webhook.url,
            match=[
                matchers.json_params_matcher(
                    {
                        "authorization_reference": "AUTH123",
                        "session_id": existing_session.uid,
                    }
                )
            ],
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["data"]["result"] == "ACCEPTED"
        assert len(responses.calls) == 1

    def test_start_session_without_webhook_returns_internal_server_error(
        self, client, nl_tst_credentials_role, ocpi_headers, valid_start_session_data
    ):
        client.credentials = nl_tst_credentials_role.credentials

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["status_code"] == 2000

    @responses.activate
    def test_start_session_with_webhook_timeout_returns_fallback_response(
        self,
        client,
        nl_tst_credentials_role,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        responses.add(
            responses.POST,
            active_start_webhook.url,
            body=ConnectionError("Connection timeout"),
        )

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["status_code"] == 2000

        assert len(responses.calls) == 1

    def test_start_session_with_inactive_webhook_returns_fallback_response(
        self, client, nl_tst_credentials_role, ocpi_headers, valid_start_session_data
    ):
        client.credentials = nl_tst_credentials_role.credentials

        WebhookFactory(
            command_type=RemoteCommandType.START_SESSION,
            active=False,
            url="https://webhook.example.com/start",
        )

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["status_code"] == 2000

    @responses.activate
    def test_start_session_with_long_field_values_validates_correctly(
        self,
        client,
        nl_tst_credentials_role,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        responses.add(
            responses.POST,
            active_start_webhook.url,
            json={"data": {"result": "REJECTED"}},
            status=200,
        )

        data = valid_start_session_data.copy()
        data["token"]["uid"] = "A" * 36
        data["location_id"] = "L" * 36

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(responses.calls) == 1

    @responses.activate
    def test_start_session_with_optional_fields_empty_works(
        self,
        client,
        nl_tst_credentials_role,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        responses.add(
            responses.POST,
            active_start_webhook.url,
            json={"data": {"result": "REJECTED"}},
            status=200,
        )

        data = valid_start_session_data.copy()
        data["evse_uid"] = ""
        data["connector_id"] = ""
        data["authorization_reference"] = ""

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(responses.calls) == 1

    def test_start_session_with_wrong_role_returns_unauthorized(
        self, client, cpo_credentials, ocpi_headers, valid_start_session_data
    ):
        client.credentials = cpo_credentials

        headers = ocpi_headers.copy()
        headers["HTTP_OCPI_FROM_PARTY_ID"] = "CPO"

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **headers,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @responses.activate
    def test_start_session_webhook_payload_always_includes_session_id_for_new_session(
        self,
        client,
        nl_tst_credentials_role,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        responses.add(
            responses.POST,
            active_start_webhook.url,
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )

        location = LocationFactory(uid=valid_start_session_data["location_id"])
        evse = EvseFactory(uid=valid_start_session_data["evse_uid"], location=location)
        _ = ConnectorFactory(uid=valid_start_session_data["connector_id"], evse=evse)

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_200_OK, f"Response: {response_data}"
        assert (
            len(responses.calls) == 1
        ), f"Expected 1 webhook call, got {len(responses.calls)}. Response: {response_data}"

        created_session = Session.objects.filter(
            authorization_reference="AUTH123",
            cdr_token__uid=valid_start_session_data["token"]["uid"],
        ).first()
        assert created_session

        webhook_payload = json.loads(responses.calls[0].request.body)
        assert webhook_payload["session_id"] == created_session.uid

    @responses.activate
    def test_start_session_webhook_payload_includes_session_id_for_existing_session(
        self,
        client,
        nl_tst_credentials_role,
        ocpi_headers,
        valid_start_session_data,
        active_start_webhook,
    ):
        client.credentials = nl_tst_credentials_role.credentials

        existing_session = OCPISessionFactory(
            authorization_reference="AUTH123",
            status=Session.PENDING,
            billed_to=nl_tst_credentials_role,
            cdr_token__uid=valid_start_session_data["token"]["uid"],
        )

        responses.add(
            responses.POST,
            active_start_webhook.url,
            match=[
                matchers.json_params_matcher(
                    {
                        "session_id": existing_session.uid,
                    }
                )
            ],
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )

        response = client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            data=valid_start_session_data,
            format="json",
            **ocpi_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(responses.calls) == 1