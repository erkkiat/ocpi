from unittest.mock import Mock

import pytest

from ocpi22.tests.factories import LocationFactory
from ocpi22.tokens.dataclasses import TokenDto
from ocpi22.tokens.token_async import process_task_result
from unittest.mock import patch
from ocpi22.tokens.token_async import authorize_with_msps_sync
from ocpi22.tokens.auth import TokenAuthorization
from ocpi22.choices import AuthorizationEnum


@pytest.fixture
def real_ocpi_221_authorization_response():
    data = {
        "allowed": "ALLOWED",
        "token": {
            "uid": "BA505A0D",
            "valid": True,
            "issuer": "NL*TNM",
            "last_updated": "2023-07-20T04:31:56Z",
            "contract_id": "BETNMC052971794",
            "party_id": "TNM",
            "type": "RFID",
            "country_code": "NL",
            "whitelist": "NEVER",
            "visual_number": "BE15KRYXW0",
        },
        "location": {
            "evse_uids": ["60100012451"],
            "location_id": "45EACA8B-F82D-11EF-B97D-029EA93F49D3",
        },
        "authorization_reference": "3cb81a6b-25a8-4df6-b2fb-b630136e639b",
    }
    return {"data": data}


@pytest.mark.django_db
def test_process_task_result_returns_correct_ocpi_master_succeeds(
    real_ocpi_221_authorization_response,
):
    successful_task = Mock()
    successful_task.result = lambda: (
        200,
        real_ocpi_221_authorization_response,
        "FR*007",
    )
    successful_task.get_name = lambda: "FR*007"
    result = process_task_result(successful_task)
    assert result["responding_party"] == "FR*007"
    assert result["msp"] == "NL*TNM"


@pytest.mark.django_db
@patch("ocpi22.tokens.token_async.asyncio.run")
def test_authorize_with_msps_sync_returns_correct_token_authorization_succeeds(
    mock_asyncio_run, real_ocpi_221_authorization_response
):
    token = "BA505A0D"
    mock_response = real_ocpi_221_authorization_response.get("data")
    mock_response["msp"] = "NL*TNM"
    mock_response["responding_party"] = "FR*007"
    mock_asyncio_run.return_value = mock_response

    result = authorize_with_msps_sync(
        TokenDto(uid=token, adhoc=True, token=None), [], LocationFactory()
    )

    mock_asyncio_run.assert_called_once()
    assert isinstance(result, TokenAuthorization)
    assert result.allowed == AuthorizationEnum.ALLOWED
    assert result.responding_party == "FR*007"
    assert result.token.ocpi_master == "NL*TNM"
    assert result.msp == "NL*TNM"
    assert result.token.uid == token
