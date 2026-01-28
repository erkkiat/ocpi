from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from django.test import override_settings
from asgiref.sync import sync_to_async

from ocpi22.locations.services import EvseServices
from ocpi22.tokens.dataclasses import TokenReference
from ocpi22.tokens.token_async import authorize_with_msps
from ocpiconnector.party import Party
from ocpi22.choices import OcpiRolesEnum
from ocpi22.tests.factories import CredentialsRoleFactory


from ocpi22.models.token import Token


@pytest.fixture
def mock_token():
    token = MagicMock(spec=Token)
    token.uid = "TEST_TOKEN_123"
    return token


@pytest.fixture
def sample_auth_data():
    return {"location_id": "LOC123", "evse_uids": ["EVSE001"]}


@pytest.fixture
async def hubject_credentials_async():
    creds_role = await sync_to_async(CredentialsRoleFactory)(
        country_code="DE",
        party_id="ICE",
        role=OcpiRolesEnum.HUB.value,
        business_details__name="Hubject",
        credentials__auth_priority=2
    )
    yield creds_role
    await sync_to_async(creds_role.credentials.delete)()


class TestHubjectFeatureFlag:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=True, HUBJECT_OPERATOR_ID="DE*ICE")
    async def test_authorize_with_msps_creates_hubject_authorize_task_when_enabled(
        self, sample_auth_data, hubject_credentials_async
    ):
        with patch(
            "ocpi22.tokens.services.TokenAuthorizationService._create_hubject_task",
            new_callable=AsyncMock,
        ) as mock_create_hubject_task:
            with patch(
                "ocpi22.tokens.services.get_our_party",
                return_value=Party("DE", "CPO"),
            ):
                with patch(
                    "ocpi22.tokens.services.get_token_id",
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
                                "ocpi22.tokens.services.CredentialsService.is_location_allowed",
                                return_value=True,
                            ):
                                token_reference = TokenReference(
                                    uid="TEST_TOKEN_123", adhoc=True, token=None
                                )
                                await authorize_with_msps(
                                    token_reference, sample_auth_data, []
                                )

                                mock_create_hubject_task.assert_called_once_with("TEST_TOKEN_123")


    @pytest.mark.asyncio
    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=False)
    async def test_authorize_with_msps_does_not_create_hubject_authorize_task_when_disabled(
        self, mock_token, sample_auth_data, hubject_credentials
    ):
        with patch(
            "integrations.hubject.services.HubjectService.post_authorize_request",
            new_callable=AsyncMock,
        ) as mock_post_authorize:
            with patch("ocpi22.tokens.token_async.asyncio.wait", return_value=([], [])):
                with patch(
                    "ocpi22.tokens.token_async.create_ssl_context",
                    return_value=AsyncMock(),
                ):
                    with patch(
                        "ocpi22.tokens.services.CredentialsService.is_location_allowed",
                        return_value=True,
                    ):
                        token_reference = TokenReference(
                            uid="SOME_TOKEN", adhoc=True, token=None
                        )
                        await authorize_with_msps(
                            token_reference, sample_auth_data, []
                        )

                        mock_post_authorize.assert_not_called()

    @override_settings(ENABLE_HUBJECT=False)
    def test_post_eroaming_push_evse_status_does_not_execute_when_disabled(self):
        with patch(
            "integrations.hubject.services.HubjectService.post_eroaming_push_evse_status"
        ) as mock_post:
            EvseServices.send_status_updates(MagicMock())
            mock_post.assert_not_called()

    @override_settings(ENABLE_HUBJECT=True)
    @pytest.mark.django_db
    def test_post_eroaming_push_evse_status_execute_once_when_enabled(
        self, hubject_credentials
    ):
        with patch(
            "integrations.hubject.services.HubjectService.post_eroaming_push_evse_status"
        ) as mock_post:
            EvseServices.send_status_updates(MagicMock())
            mock_post.assert_called_once()
