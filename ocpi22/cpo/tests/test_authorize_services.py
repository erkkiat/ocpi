from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import responses
from django.test import override_settings
from responses import matchers

from ocpi22.tokens.token_async import authorize_with_msps
from ocpiconnector.party import Party

from ocpi22.tasks import send_hubject_request

from ocpi22.models.token import Token


@pytest.fixture
def mock_token():
    token = MagicMock(spec=Token)
    token.uid = "TEST_TOKEN_123"
    return token


@pytest.fixture
def sample_auth_data():
    return {"location_id": "LOC123", "evse_uids": ["EVSE001"]}


class TestHubjectFeatureFlag:
    @pytest.mark.asyncio
    @override_settings(ENABLE_HUBJECT=True, HUBJECT_OPERATOR_ID="DE*ICE")
    async def test_authorize_with_msps_creates_hubject_authorize_task_when_enabled(
        self, mock_token, sample_auth_data
    ):
        with patch(
            "integrations.hubject.services.HubjectService"
        ) as mock_hubject_service:
            with patch(
                "ocpi22.tokens.token_async.get_our_party",
                return_value=Party("DE", "CPO"),
            ):
                with patch(
                    "ocpi22.tokens.token_async.get_token_id",
                    return_value="TEST_TOKEN_123",
                ):
                    with patch(
                        "ocpi22.tokens.token_async.asyncio.wait", return_value=([], [])
                    ):
                        with patch(
                            "ocpi22.tokens.token_async.create_ssl_context",
                            return_value=AsyncMock(),
                        ):
                            with patch(
                                "ocpi22.tokens.token_async.sync_to_async",
                                return_value=AsyncMock(return_value=MagicMock()),
                            ):
                                mock_hubject_service.post_authorize_request = (
                                    AsyncMock()
                                )

                                await authorize_with_msps(
                                    mock_token, sample_auth_data, []
                                )

                                mock_hubject_service.post_authorize_request.assert_called_once_with(
                                    operator_id="DE*CPO",
                                    token_id="TEST_TOKEN_123",
                                )

    @pytest.mark.asyncio
    @override_settings(ENABLE_HUBJECT=False)
    async def test_authorize_with_msps_does_not_create_hubject_authorize_task_when_disabled(
        self, mock_token, sample_auth_data
    ):
        with patch(
            "integrations.hubject.services.HubjectService"
        ) as mock_hubject_service:
            with patch("ocpi22.tokens.token_async.asyncio.wait", return_value=([], [])):
                with patch(
                    "ocpi22.tokens.token_async.create_ssl_context",
                    return_value=AsyncMock(),
                ):
                    with patch(
                        "ocpi22.tokens.token_async.sync_to_async",
                        return_value=AsyncMock(return_value=MagicMock()),
                    ):
                        mock_hubject_service.post_authorize_request = AsyncMock()

                        await authorize_with_msps(mock_token, sample_auth_data, [])

                        mock_hubject_service.post_authorize_request.assert_not_called()

    @override_settings(ENABLE_HUBJECT=False)
    def test_send_hubject_request_returns_none_when_disabled(self):
        result = send_hubject_request({}, "http://example.com", "post")
        assert result is None

    @responses.activate
    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=True)
    def test_send_hubject_request_successfully(self, caplog):
        HUBJECT_URL = "https://hubject-api.com/endpoint"
        responses.add(
            responses.PUT,
            HUBJECT_URL,
            json={"success": True},
            status=200,
            match=[matchers.json_params_matcher({"key": "value"})],
        )
        with patch.object(send_hubject_request, "app") as mock_app:
            mock_app.conf.task_always_eager = False
            result = send_hubject_request({"key": "value"}, HUBJECT_URL)
            assert result is None
            assert (
                "Sending hubject put request to https://hubject-api.com/endpoint"
                in caplog.text
            )
