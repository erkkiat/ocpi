import requests
import responses
import pytest

import integrations.hubject.services as services
from integrations.hubject.services import HubjectService


@responses.activate
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_post_authorize_request_does_not_raise_sync_error(hubject_credentials):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        json={"StatusCode": {"Code": "017"}, "ProviderID": "DE*XYZ"},
        status=200,
    )

    status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )

    assert status_code == 200
    assert mapped is None
    assert ocpi_master is None


@responses.activate
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_post_authorize_request_returns_succeeds(hubject_credentials):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        json={
            "StatusCode": {"Code": "000"},
            "ProviderID": "DE*MSP",
            "SessionID": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
            "AuthorizationStatus": "Authorized",
        },
        status=200,
    )

    status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )

    assert status_code == 200
    assert mapped is not None
    assert ocpi_master is not None
    assert ocpi_master.country_code == "DE"
    assert ocpi_master.party_id == "MSP"


@responses.activate
@pytest.mark.asyncio
async def test_post_authorize_request_returns_success_and_ocpi_master(monkeypatch):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        json={"StatusCode": {"Code": "000"}, "ProviderID": "DE*XYZ"},
        status=200,
    )

    def fake_get_credentialsrole(*args, **kwargs):
        return "FR*ABC"

    mock_session = requests.Session()
    monkeypatch.setattr(
        HubjectService, "_get_hubject_credentials_id", staticmethod(lambda: 1)
    )
    monkeypatch.setattr(
        services, "get_certificate_loaded_request", lambda cred_id: mock_session
    )
    monkeypatch.setattr(services, "get_credentialsrole", fake_get_credentialsrole)
    monkeypatch.setattr(
        services,
        "map_successful_oicp_authorization_response_to_ocpi_221",
        lambda data, token: {"mapped": token},
    )
    status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 200
    assert mapped == {"mapped": "E4CEA229D30A523A19CC"}
    assert ocpi_master == "FR*ABC"


@responses.activate
@pytest.mark.asyncio
async def test_post_authorize_request_returns_success_without_ocpi_master_when_status_code_not_000(
    monkeypatch,
):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        json={"StatusCode": {"Code": "123"}, "ProviderID": "DEXYZ"},
        status=200,
    )
    mock_session = requests.Session()
    monkeypatch.setattr(
        HubjectService, "_get_hubject_credentials_id", staticmethod(lambda: 1)
    )
    monkeypatch.setattr(
        services, "get_certificate_loaded_request", lambda cred_id: mock_session
    )
    monkeypatch.setattr(
        services,
        "map_successful_oicp_authorization_response_to_ocpi_221",
        lambda data, token: {"mapped": token},
    )
    status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 200
    assert mapped is None
    assert ocpi_master is None


@responses.activate
@pytest.mark.asyncio
async def test_post_authorize_request_logs_warning_when_status_code_not_000(
    monkeypatch, caplog
):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        json={"StatusCode": {"Code": "017"}, "ProviderID": "DE*XYZ"},
        status=200,
    )
    mock_session = requests.Session()
    monkeypatch.setattr(
        HubjectService, "_get_hubject_credentials_id", staticmethod(lambda: 1)
    )
    monkeypatch.setattr(
        services, "get_certificate_loaded_request", lambda cred_id: mock_session
    )
    with caplog.at_level("WARNING"):
        await HubjectService.post_authorize_request("DE*XYZ", "E4CEA229D30A523A19CC")
    assert (
        "Authorization failed with status code 200 and Hubject error code 017 (Unauthorized Access)"
        in caplog.text
    )


@responses.activate
@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_oserror(monkeypatch):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        body=requests.exceptions.ConnectionError("Network error occurred"),
    )
    mock_session = requests.Session()
    monkeypatch.setattr(
        HubjectService, "_get_hubject_credentials_id", staticmethod(lambda: 1)
    )
    monkeypatch.setattr(
        services, "get_certificate_loaded_request", lambda cred_id: mock_session
    )
    status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master is None


@responses.activate
@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_runtime_error(monkeypatch):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        body=requests.exceptions.Timeout("Network error occurred"),
    )
    mock_session = requests.Session()
    monkeypatch.setattr(
        HubjectService, "_get_hubject_credentials_id", staticmethod(lambda: 1)
    )
    monkeypatch.setattr(
        services, "get_certificate_loaded_request", lambda cred_id: mock_session
    )
    status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master is None
