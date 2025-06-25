import pytest
from datetime import datetime as real_datetime

import integrations.hubject.services as services
from integrations.hubject.services import HubjectService
from django.conf import settings


class DummyResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = str(json_data)

    def json(self):
        return self._json

    def get(self, key, default=None):
        return self._json.get(key, default)


class FakeDateTime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2020, 1, 1, 12, 0, 0, tzinfo=tz)


@pytest.fixture(autouse=True)
def freeze_time(monkeypatch):
    monkeypatch.setattr(services, "datetime", FakeDateTime)
    monkeypatch.setattr(settings, "OCPI_DATE_FORMAT", "%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.asyncio
async def test_post_authorize_request_returns_success_and_ocpi_master(monkeypatch):
    dummy_json = {"StatusCode": {"Code": "000"}, "ProviderID": "DE*XYZ"}
    monkeypatch.setattr(
        services.HubjectService.client,
        "post",
        lambda url, json: DummyResponse(200, dummy_json),
    )

    async def fake_role(*args, **kwargs):
        return "fake_role"

    monkeypatch.setattr(services, "sync_to_async", lambda func: fake_role)
    monkeypatch.setattr(
        services,
        "map_oicp_authorization_response_to_ocpi_221",
        lambda data, token: {"mapped": token},
    )
    status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 200
    assert mapped == {"mapped": "E4CEA229D30A523A19CC"}
    assert ocpi_master == "fake_role"


@pytest.mark.asyncio
async def test_post_authorize_request_returns_success_without_ocpi_master_when_status_code_not_000(
    monkeypatch,
):
    dummy_json = {"StatusCode": {"Code": "123"}, "ProviderID": "DE*XYZ"}
    monkeypatch.setattr(
        services.HubjectService.client,
        "post",
        lambda url, json: DummyResponse(200, dummy_json),
    )
    # leave sync_to_async unpatched so ocpi_master stays None
    monkeypatch.setattr(
        services,
        "map_oicp_authorization_response_to_ocpi_221",
        lambda data, token: {"mapped": token},
    )
    status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 200
    assert mapped == {"mapped": "E4CEA229D30A523A19CC"}
    assert ocpi_master is None


@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_value_error(monkeypatch):
    monkeypatch.setattr(
        services.HubjectService.client,
        "post",
        lambda url, json: (_ for _ in ()).throw(ValueError("bad")),
    )
    status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 404
    assert error_dict["allowed"] == "NOT_ALLOWED"
    assert "timestamp" in error_dict
    assert ocpi_master.count() == 0


@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_oserror(monkeypatch):
    monkeypatch.setattr(
        services.HubjectService.client,
        "post",
        lambda url, json: (_ for _ in ()).throw(OSError("net")),
    )
    status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 404
    assert error_dict["status_message"] == "Network error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master.count() == 0


@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_runtime_error(monkeypatch):
    monkeypatch.setattr(
        services.HubjectService.client,
        "post",
        lambda url, json: (_ for _ in ()).throw(RuntimeError("oops")),
    )
    status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
        "DE*XYZ", "E4CEA229D30A523A19CC"
    )
    assert status_code == 404
    assert error_dict["status_message"] == "Unexpected runtime error"
    assert "timestamp" in error_dict
    assert ocpi_master.count() == 0
