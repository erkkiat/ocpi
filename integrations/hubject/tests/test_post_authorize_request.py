import requests
import responses
import pytest

import integrations.hubject.services as services
from integrations.hubject.services import HubjectService


@responses.activate
@pytest.mark.asyncio
async def test_post_authorize_request_returns_success_and_ocpi_master(monkeypatch):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        json={"StatusCode": {"Code": "000"}, "ProviderID": "DE*XYZ"},
        status=200,
    )

    async def fake_role(*args, **kwargs):
        return "FR*ABC"

    monkeypatch.setattr(services, "sync_to_async", lambda func: fake_role)
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
    # leave sync_to_async unpatched so ocpi_master stays None
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
async def test_post_authorize_request_returns_error_tuple_on_oserror(monkeypatch):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        body=requests.exceptions.ConnectionError("Network error occurred"),
    )
    status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred", error_dict
    assert "timestamp" in error_dict
    assert ocpi_master.count() == 0


@responses.activate
@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_runtime_error(monkeypatch):
    responses.add(
        method=responses.POST,
        url="https://service-qa.hubject.com/api/oicp/charging/v21/operators/DE*XYZ/authorize/start",
        body=requests.exceptions.Timeout("Network error occurred"),
    )
    status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred", error_dict
    assert "timestamp" in error_dict
    assert ocpi_master.count() == 0
