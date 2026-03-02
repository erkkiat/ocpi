import pytest

from django.test import override_settings

from integrations.hubject.services import HubjectService
import integrations.hubject.services as services
from aiohttp import ClientError, ClientSession
import asyncio
from aioresponses import aioresponses
from django.conf import settings


@pytest.fixture
async def client_session():
    async with ClientSession() as session:
        yield session


@pytest.mark.django_db
@pytest.mark.asyncio
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_succeeds(
    hubject_credentials_async, client_session
):
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
            status=200,
        )

        status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 200
    assert mapped is not None
    assert ocpi_master is not None
    assert ocpi_master.country_code == "DE"
    assert ocpi_master.party_id == "MSP"


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_success_and_ocpi_master(
    monkeypatch, hubject_credentials_async, client_session
):
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
            status=200,
        )

        status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 200
    assert mapped == {"mapped": "E4CEA229D30A523A19CC"}
    assert ocpi_master == "FR*ABC"


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_success_without_ocpi_master_when_status_code_not_000(
    monkeypatch, hubject_credentials_async, client_session
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
            status=200,
        )

        status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 200
    assert mapped is None
    assert ocpi_master is None


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_logs_warning_when_status_code_not_000(
    monkeypatch, caplog, hubject_credentials_async, client_session
):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={"StatusCode": {"Code": "017"}, "ProviderID": "DE*XYZ"},
            status=200,
        )

        with caplog.at_level("WARNING"):
            await HubjectService.post_authorize_request(
                "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
            )

    assert (
        "Authorization failed with status code 200 and Hubject error code 017 (Unauthorized Access)"
        in caplog.text
    )


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_error_tuple_on_oserror(
    monkeypatch, client_session, hubject_credentials_async
):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(url, exception=ClientError("Network error occurred"))

        (
            status_code,
            error_dict,
            ocpi_master,
        ) = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_post_authorize_request_returns_error_tuple_on_runtime_error(
    monkeypatch, client_session
):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(url, exception=asyncio.TimeoutError("Timeout occurred"))

        (
            status_code,
            error_dict,
            ocpi_master,
        ) = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 404
    assert error_dict["status_message"] == "Request error occurred"
    assert "timestamp" in error_dict
    assert ocpi_master is None


@pytest.mark.asyncio
@pytest.mark.django_db
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_returns_500_on_processing_error(
    monkeypatch, hubject_credentials_async, client_session
):
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
            status=200,
        )

        (
            status_code,
            error_dict,
            ocpi_master,
        ) = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 500
    assert error_dict["status_message"] == ""
    assert "timestamp" in error_dict
    assert ocpi_master is None


@pytest.mark.django_db
@pytest.mark.asyncio
@override_settings(ENABLE_HUBJECT=True)
async def test_post_authorize_request_handles_dash_separated_provider_id(
    hubject_credentials_async, client_session
):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={
                "StatusCode": {"Code": "000"},
                "ProviderID": "NL-TNM",
                "SessionID": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
                "AuthorizationStatus": "Authorized",
            },
            status=200,
        )

        status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 200
    assert mapped is not None
    assert ocpi_master is not None
    assert ocpi_master.country_code == "NL"
    assert ocpi_master.party_id == "TNM"


@pytest.mark.django_db
@pytest.mark.asyncio
@override_settings(ENABLE_HUBJECT=True)
@pytest.mark.parametrize(
    "provider_id,expected_country_code,expected_party_id",
    [
        ("NL-TNM", "NL", "TNM"),
        ("DE*MSP", "DE", "MSP"),
        ("FRXYZ", "FR", "XYZ"),
    ],
)
async def test_post_authorize_request_parses_provider_id_formats(
    hubject_credentials_async,
    client_session,
    provider_id,
    expected_country_code,
    expected_party_id,
):
    url = f"{settings.HUBJECT_URL}charging/v21/operators/DE*XYZ/authorize/start"

    with aioresponses() as mocked_responses:
        mocked_responses.post(
            url,
            payload={
                "StatusCode": {"Code": "000"},
                "ProviderID": provider_id,
                "SessionID": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
                "AuthorizationStatus": "Authorized",
            },
            status=200,
        )

        status_code, mapped, ocpi_master = await HubjectService.post_authorize_request(
            "DE*XYZ", "E4CEA229D30A523A19CC", session=client_session
        )

    assert status_code == 200
    assert ocpi_master is not None
    assert ocpi_master.country_code == expected_country_code
    assert ocpi_master.party_id == expected_party_id
