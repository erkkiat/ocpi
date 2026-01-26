import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from django.test import override_settings

from ocpi22.tokens.dataclasses import PartyDetails
from ocpi22.tokens.services import TokenAuthorizationService
from ocpi22.tokens.token_async import AuthorizationEnum
from ocpi22.models.credentials import Credentials
from ocpi22.tests.factories import CredentialsRoleFactory
from ocpi22.choices import OcpiRolesEnum
from asgiref.sync import sync_to_async


@pytest.fixture
def party_details():
    def _create_party_details(priority, pid, delay=0, allowed=True):
        return PartyDetails(
            url=f"http://{pid}.com",
            headers={},
            ssl=None,
            ocpi_master=MagicMock(),
            party_id=pid,
            country_code="DE",
            credentials=MagicMock(spec=Credentials),
            task_name=f"DE*{pid}",
            auth_priority=priority,
            _delay=delay,
            _allowed=allowed,
        )

    return _create_party_details


@pytest.fixture
def token_service():
    return TokenAuthorizationService()


class TestAdhocTokenAuthorization:
    def _create_side_effect(self, parties, task_states=None):
        async def side_effect(session, url, **kwargs):
            p = next(p for p in parties if p.url == url)
            try:
                await asyncio.sleep(p._delay)
                if task_states is not None:
                    task_states[p.party_id] = "completed"

                allowed_enum = (
                    AuthorizationEnum.ALLOWED
                    if p._allowed
                    else AuthorizationEnum.NOT_ALLOWED
                )
                return (
                    200,
                    {"data": {"allowed": allowed_enum, "token": {"uid": "t"}}},
                    p.ocpi_master,
                )
            except asyncio.CancelledError:
                if task_states is not None:
                    task_states[p.party_id] = "cancelled"
                raise
        return side_effect

    @pytest.mark.django_db
    async def test_ranking_priority_when_more_than_one_party_returns_allowed(
        self, party_details, token_service, hubject_credentials
    ):
        mock_session = AsyncMock()
        await sync_to_async(Credentials.objects.filter(pk=hubject_credentials.pk).update)(auth_priority=2)

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
                assert result["responding_party"] == "DE*OWN"

    @pytest.mark.django_db
    async def test_ranking_priority_when_party_returns_allowed_and_other_party_returns_not_allowed(
        self, mock_party_details, token_service, hubject_credentials
    ):
        mock_session = AsyncMock()
        await sync_to_async(Credentials.objects.filter(pk=hubject_credentials.pk).update)(auth_priority=2)

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
        self, mock_party_details, token_service, hubject_credentials
    ):
        mock_session = AsyncMock()
        await sync_to_async(Credentials.objects.filter(pk=hubject_credentials.pk).update)(auth_priority=2)

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
        self, mock_party_details, token_service, hubject_credentials
    ):
        mock_session = AsyncMock()
        await sync_to_async(Credentials.objects.filter(pk=hubject_credentials.pk).update)(auth_priority=2)

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
