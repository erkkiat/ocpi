
import pytest

from django.test import override_settings

from integrations.hubject.services import HubjectService
import integrations.hubject.services as services
from aiohttp import ClientError, ClientSession
import asyncio
from aioresponses import aioresponses
from django.conf import settings

@pytest.mark.django_db
@pytest.mark.asyncio
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_succeeds(hubject_credentials_async):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={
                "StatusCode": {"Code": "000"},
                "ProviderID": "DE*MSP",
                "SessionID": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
                "AuthorizationStatus": "Authorized",
            },
            status=200
        )
        
        async with ClientSession() as session:
            status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=session
            )

    assert status_code == 200
    assert mapped is not None
    assert ocpi_master is not None
    assert ocpi_master.country_code == "DE"
    assert ocpi_master.party_id == "MSP"


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_success_and_ocpi_master(monkeypatch, hubject_credentials_async):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    def fake_get_credentialsrole(*args, **kwargs):
        return "FR*ABC"

    monkeypatch.setattr(services, "get_credentialsrole", fake_get_credentialsrole)
    monkeypatch.setattr(
        services,
        "map_successful_oicp_authorization_response_to_ocpi_221",
        lambda data, token: {"mapped": token},
    )
    
    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={"StatusCode": {"Code": "000"}, "ProviderID": "DE*XYZ"},
            status=200
        )
        
        async with ClientSession() as session:
            status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=session
            )
    
    assert status_code == 200
    assert mapped == {"mapped": "E4CEA229D30A523A19CC"}
    assert ocpi_master == "FR*ABC"


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_success_without_ocpi_master_when_status_code_not_000(
    monkeypatch, hubject_credentials_async
):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    monkeypatch.setattr(
        services,
        "map_successful_oicp_authorization_response_to_ocpi_221",
        lambda data, token: {"mapped": token},
    )
    
    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={"StatusCode": {"Code": "123"}, "ProviderID": "DEXYZ"},
            status=200
        )

        async with ClientSession() as session:
            status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=session
            )

    assert status_code == 200
    assert mapped is None
    assert ocpi_master is None


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_logs_warning_when_status_code_not_000(
    monkeypatch, caplog, hubject_credentials_async
):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={"StatusCode": {"Code": "017"}, "ProviderID": "DE*XYZ"},
            status=200
        )
        
        async with ClientSession() as session:
            with caplog.at_level("WARNING"):
                await HubjectService.post_authorize_request(
                    "DE*XYZ", "E4CEA229D30A523A19CC", session=session
                )
    
    assert (
        "Authorization failed with status code 200 and Hubject error code 017 (Unauthorized Access)"
        in caplog.text
    )


@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_oserror(monkeypatch):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(url, exception=ClientError("Network error occurred"))
        
        async with ClientSession() as session:
            status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=session
            )

    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master is None


@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_runtime_error(monkeypatch):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(url, exception=asyncio.TimeoutError("Timeout occurred"))
        
        async with ClientSession() as session:
            status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=session
            )

    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master is None


@pytest.mark.asyncio
async def test_post_authorize_request_returns_error_tuple_on_generic_exception(monkeypatch):
    # This test simulates an exception during the HTTP request setup or execution that falls into the generic Exception block
    # However, since we are using aioresponses, triggering a generic Exception specifically 'connecting' might be hard if it's not one of the caught ones.
    # But checking the code, 'except Exception' is at the end.
    # We can mock side_effect on the session if we really wanted to, but we are using real session.
    # aioresponses 'exception' argument raises the exception when request is called.
    
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(url, exception=Exception("Unexpected error"))
        
        async with ClientSession() as session:
            status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=session
            )
            
    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master is None


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_500_on_processing_error(monkeypatch, hubject_credentials_async):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    def fake_get_credentialsrole(*args, **kwargs):
        raise Exception("Processing error")

    monkeypatch.setattr(services, "get_credentialsrole", fake_get_credentialsrole)
    monkeypatch.setattr(
        services,
        "map_successful_oicp_authorization_response_to_ocpi_221",
        lambda data, token: {"mapped": token},
    )
    
    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={"StatusCode": {"Code": "000"}, "ProviderID": "DE*XYZ"},
            status=200
        )
        
        async with ClientSession() as session:
            status_code, error_dict, ocpi_master = await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=session
            )
    
    assert status_code == 500
    assert error_dict["status_message"] == ""
    assert "timestamp" in error_dict
    assert ocpi_master is None
