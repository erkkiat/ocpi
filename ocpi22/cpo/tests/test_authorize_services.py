from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from django.test import override_settings

from ocpi22.locations.services import EvseServices
from ocpi22.tokens.token_async import authorize_with_msps
from ocpiconnector.party import Party


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
    def test_post_eroaming_push_evse_status_does_not_execute_when_disabled(self):
        with patch(
            "integrations.hubject.services.HubjectService.post_eroaming_push_evse_status"
        ) as mock_post:
            EvseServices.send_status_updates(MagicMock())
            mock_post.assert_not_called()

    @override_settings(ENABLE_HUBJECT=True)
    def test_post_eroaming_push_evse_status_execute_once_when_enabled(self):
        with patch(
            "integrations.hubject.services.HubjectService.post_eroaming_push_evse_status"
        ) as mock_post:
            EvseServices.send_status_updates(MagicMock())
            mock_post.assert_called_once()
