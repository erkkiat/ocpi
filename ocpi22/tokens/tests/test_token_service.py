import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from django.test import override_settings

from ocpi22.tokens.dataclasses import PartyDetails
from ocpi22.tokens.services import TokenAuthorizationService
from ocpi22.tokens.token_async import AuthorizationEnum
from ocpi22.tests.factories import CredentialsRoleFactory, CredentialsFactory, OCPISessionFactory, LocationFactory, \
    EvseFactory
from ocpi22.choices import OcpiRolesEnum
from asgiref.sync import sync_to_async

@pytest.fixture
def location():
    location =  LocationFactory(
        uid="LOC1",
    )
    EvseFactory(
        location=location,
        uid="EVSE1",
    )
    return location


@pytest.fixture
def party_details(location):
    def _create_party_details(priority, country_code, party_id, delay=0, allowed=True, hub=False):
        credentials = CredentialsFactory(
            auth_priority=priority,
            allowed_locations=[location.uid]
        )
        role = CredentialsRoleFactory(
            country_code=country_code,
            party_id=party_id,
            role=OcpiRolesEnum.HUB.value if hub else OcpiRolesEnum.EMSP.value,
            credentials=credentials,
        )
        party_details = PartyDetails(
            url=f"http://{country_code}-{party_id}-{credentials.theirs}.com",
            headers={},
            ssl=None,
            ocpi_master=role,
            party_id=party_id,
            country_code=country_code,
            credentials=credentials,
            task_name=f"{country_code}*{party_id}",
            auth_priority=priority,
        )
        return {
            "party_details": party_details,
            "_delay": delay,
            "_allowed": allowed,
        }

    return _create_party_details


@pytest.fixture
def token_service():
    return TokenAuthorizationService()


class TestAdhocTokenAuthorization:
    def _create_delayed_post_request(self, parties):
        async def delayed_post_request(session, url, data, ocpi_master, **kwargs):
            party = next(party for party in parties if party["party_details"].url == url)
            await asyncio.sleep(party["_delay"])

            party_details = party["party_details"]
            allowed = (
                AuthorizationEnum.ALLOWED
                if party["_allowed"]
                else AuthorizationEnum.NOT_ALLOWED
            )
            return (
                200,
                {"data": {"allowed": allowed, "token": {"uid": "t"}}},
                party_details.ocpi_master,
            )
        return delayed_post_request

    @pytest.mark.django_db
    async def test_ranking_priority_when_more_than_one_party_returns_allowed(
        self, party_details, token_service, hubject_credentials, location
    ):
        session = await sync_to_async(OCPISessionFactory)()

        msp_fr_111 = await sync_to_async(party_details)(priority=2, country_code="FR", party_id="111", allowed=True)
        msp_fi_msp = await sync_to_async(party_details)(priority=3, country_code="FI", party_id="MSP", allowed=True)
        parties = [msp_fr_111, msp_fi_msp]

        delayed_post_request = self._create_delayed_post_request(parties)

        parties_details = [party["party_details"] for party in parties]

        with patch("ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request):
            result = await token_service.authorize_adhoc_token(
                parties_details, session, {"location_id": location.uid}, "ADHOC"
            )

            assert result is not None
            assert result["allowed"] == AuthorizationEnum.ALLOWED
            assert result["responding_party"] == "FR*111"

    @pytest.mark.django_db
    async def test_ranking_priority_when_party_returns_allowed_and_other_party_returns_not_allowed(
        self, mock_party_details, token_service, hubject_credentials_async
    ):
        mock_session = AsyncMock()

        p2 = party_details()
        p0 = party_details()
        parties = [p2, p0]

        side_effect = self._create_side_effect(parties)

        with patch(
            "ocpi22.tokens.services.CredentialsService.is_location_allowed",
            return_value=True,
        ):
            with patch("ocpi22.tokens.token_async.post_request", side_effect=side_effect):
                result = await token_service.authorize_adhoc_token(
                    parties, mock_session, {}, "ADHOC"
                )

                assert result is not None
                assert result["allowed"] == AuthorizationEnum.ALLOWED

    @pytest.mark.django_db
    async def test_waiting_for_higher_ranked_party_when_lower_ranked_party_returns_allowed_fast(
        self, mock_party_details, token_service, hubject_credentials_async
    ):
        mock_session = AsyncMock()

        p2 = party_details()
        p0 = party_details()
        parties = [p2, p0]
        task_states = {}

        side_effect = self._create_side_effect(parties, task_states)

        with patch(
            "ocpi22.tokens.services.CredentialsService.is_location_allowed",
            return_value=True,
        ):
            with patch("ocpi22.tokens.token_async.post_request", side_effect=side_effect):
                result = await token_service.authorize_adhoc_token(
                    parties, mock_session, {}, "ADHOC"
                )

                assert result is not None
                assert result["allowed"] == AuthorizationEnum.ALLOWED
                assert result["responding_party"] == "DE*HUB"

                assert task_states.get("OWN") == "completed"

    @pytest.mark.django_db
    async def test_authorize_adhoc_token_returns_none_when_timeout_occurs(
        self, mock_party_details, token_service, hubject_credentials_async
    ):
        mock_session = AsyncMock()

        p0 = party_details()
        parties = [p0]

        async def side_effect(session, url, **kwargs):
            await asyncio.sleep(0.3)
            return (200, {"data": {"allowed": "ALLOWED", "token": {"uid": "t"}}}, None)

        token_service._timeout = 0.1
        
        with patch(
            "ocpi22.tokens.services.CredentialsService.is_location_allowed",
            return_value=True,
        ):
            with patch("ocpi22.tokens.token_async.post_request", side_effect=side_effect):
                result = await token_service.authorize_adhoc_token(
                    parties, mock_session, {}, "ADHOC"
                )
                assert result is None

    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=True)
    async def test_authorize_adhoc_token_executes_hubject_task(
        self, mock_party_details, token_service
    ):
        mock_session = AsyncMock()
        await sync_to_async(CredentialsRoleFactory)(
            country_code="DE",
            party_id="ICE",
            role=OcpiRolesEnum.HUB.value,
            business_details__name="Hubject",
            credentials__auth_priority=2
        )

        p9 = party_details()
        parties = [p9]

        with patch(
            "integrations.hubject.services.HubjectService.post_authorize_request",
            new_callable=AsyncMock,
        ) as mock_hubject:
            mock_hubject.return_value = (
                200,
                {"data": {"allowed": "ALLOWED", "token": {"uid": "t"}}},
                None,
            )

            with patch(
                "ocpi22.tokens.token_async.post_request", new_callable=AsyncMock
            ) as mock_post:
                mock_post.return_value = (
                    200,
                    {"data": {"allowed": "NOT_ALLOWED", "token": {"uid": "t"}}},
                    None,
                )

                with patch(
                    "ocpi22.tokens.services.CredentialsService.is_location_allowed",
                    return_value=True,
                ):
                    result = await token_service.authorize_adhoc_token(
                        parties, mock_session, {}, "ADHOC"
                    )

                    assert result is not None
                    assert result["allowed"] == AuthorizationEnum.ALLOWED
                    mock_hubject.assert_called_once()


class TestTokenAuthorizationServiceHelperMethods:
    def test_has_better_ranks_pending(self, token_service):
        task1 = MagicMock(spec=asyncio.Task)
        task2 = MagicMock(spec=asyncio.Task)

        tasks_map = {task1: 2, task2: 4}
        pending = {task1, task2}

        assert token_service._has_better_ranks_pending(3, tasks_map, pending) is True
        assert token_service._has_better_ranks_pending(1, tasks_map, pending) is False

    def test_cancel_pending_tasks(self, token_service):
        task1 = MagicMock(spec=asyncio.Task)
        task2 = MagicMock(spec=asyncio.Task)
        pending = {task1, task2}

        token_service._cancel_pending_tasks(pending)

        task1.cancel.assert_called_once()
        task2.cancel.assert_called_once()


@pytest.mark.asyncio
class TestKnownTokenAuthorization:
    async def test_return_allowed_response(
        self, mock_party_details, token_service
    ):
        mock_session = AsyncMock()
        party = party_details()
        unified_token_id = "TOKEN1"
        data = {"test": "data"}

        with patch(
            "ocpi22.tokens.token_async.post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = (
                200,
                {"data": {"allowed": AuthorizationEnum.ALLOWED, "token": {"uid": "t"}}},
                party.ocpi_master,
            )

            result = await token_service.authorize_known_token(
                [party], mock_session, data, unified_token_id
            )

            assert result is not None
            assert result["allowed"] == AuthorizationEnum.ALLOWED
            mock_post.assert_called_once()
            assert mock_post.call_args[1]["url"] == party.url

    async def test_return_not_allowed_response(
        self, mock_party_details, token_service
    ):
        mock_session = AsyncMock()
        party = party_details()

        with patch(
            "ocpi22.tokens.token_async.post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = (
                200,
                {
                    "data": {
                        "allowed": AuthorizationEnum.NOT_ALLOWED,
                        "token": {"uid": "t"},
                    }
                },
                party.ocpi_master,
            )

            result = await token_service.authorize_known_token(
                [party], mock_session, {}, "T1"
            )
            assert result is not None
            assert result["allowed"] == AuthorizationEnum.NOT_ALLOWED
