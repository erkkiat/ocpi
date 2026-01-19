import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from ocpi22.tokens.services import TokenAuthorizationService
from ocpi22.tokens.token_async import AuthorizationEnum
from ocpi22.models.credentials import Credentials


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def mock_party_details():
    def _create_party(rank, pid, delay=0, allowed=True):
        return {
            "url": f"http://{pid}.com",
            "headers": {},
            "ssl": None,
            "ocpi_master": MagicMock(),
            "party_id": pid,
            "country_code": "DE",
            "credentials": MagicMock(spec=Credentials),
            "task_name": f"DE*{pid}",
            "rank": rank,
            "_delay": delay,
            "_allowed": allowed,
        }

    return _create_party


@pytest.fixture
def token_service():
    return TokenAuthorizationService()


class TestAdhocTokenAuthorization:
    @pytest.mark.django_db
    async def test_ranking_priority_when_more_than_one_party_returns_allowed(
        self, mock_session, mock_party_details, token_service, hubject_credentials
    ):
        p2 = mock_party_details(rank=2, pid="HUB", delay=0.01, allowed=True)
        p0 = mock_party_details(rank=0, pid="OWN", delay=0.05, allowed=True)

        parties = [p2, p0]

        async def side_effect(session, url, **kwargs):
            p = next(p for p in parties if p["url"] == url)
            await asyncio.sleep(p["_delay"])
            allowed_enum = (
                AuthorizationEnum.ALLOWED
                if p["_allowed"]
                else AuthorizationEnum.NOT_ALLOWED
            )
            return (
                200,
                {"data": {"allowed": allowed_enum, "token": {"uid": "t"}}},
                p["ocpi_master"],
            )

        with patch("ocpi22.tokens.token_async.post_request", side_effect=side_effect):
            with patch(
                "ocpi22.credentials.services.CredentialsService.get_hubject_priority_rank",
                return_value=2,
            ):
                result = await token_service.authorize_adhoc_token(
                    parties, mock_session, {}, "ADHOC"
                )

                assert result is not None
                assert result["allowed"] == AuthorizationEnum.ALLOWED
                assert result["responding_party"] == "DE*OWN"

    @pytest.mark.django_db
    async def test_ranking_priority_when_party_returns_allowed_and_other_party_returns_not_allowed(
        self, mock_session, mock_party_details, token_service, hubject_credentials
    ):
        p2 = mock_party_details(rank=2, pid="HUB", delay=0.01, allowed=True)
        p0 = mock_party_details(rank=0, pid="OWN", delay=0.05, allowed=False)

        parties = [p2, p0]

        async def side_effect(session, url, **kwargs):
            p = next(p for p in parties if p["url"] == url)
            await asyncio.sleep(p["_delay"])
            allowed_enum = (
                AuthorizationEnum.ALLOWED
                if p["_allowed"]
                else AuthorizationEnum.NOT_ALLOWED
            )
            return (
                200,
                {"data": {"allowed": allowed_enum, "token": {"uid": "t"}}},
                p["ocpi_master"],
            )

        with patch("ocpi22.tokens.token_async.post_request", side_effect=side_effect):
            with patch(
                "ocpi22.credentials.services.CredentialsService.get_hubject_priority_rank",
                return_value=2,
            ):
                result = await token_service.authorize_adhoc_token(
                    parties, mock_session, {}, "ADHOC"
                )

                assert result is not None
                assert result["allowed"] == AuthorizationEnum.ALLOWED

    @pytest.mark.django_db
    async def test_waiting_for_higher_ranked_party_when_lower_ranked_party_returns_allowed_fast(
        self, mock_session, mock_party_details, token_service, hubject_credentials
    ):
        p2 = mock_party_details(rank=2, pid="HUB", delay=0.01, allowed=True)
        p0 = mock_party_details(rank=0, pid="OWN", delay=0.05, allowed=False)

        parties = [p2, p0]
        task_states = {}

        async def side_effect(session, url, **kwargs):
            p = next(p for p in parties if p["url"] == url)
            try:
                await asyncio.sleep(p["_delay"])
                task_states[p["party_id"]] = "completed"
                allowed_enum = (
                    AuthorizationEnum.ALLOWED
                    if p["_allowed"]
                    else AuthorizationEnum.NOT_ALLOWED
                )
                return (
                    200,
                    {"data": {"allowed": allowed_enum, "token": {"uid": "t"}}},
                    p["ocpi_master"],
                )
            except asyncio.CancelledError:
                task_states[p["party_id"]] = "cancelled"
                raise

        with patch("ocpi22.tokens.token_async.post_request", side_effect=side_effect):
            with patch(
                "ocpi22.credentials.services.CredentialsService.get_hubject_priority_rank",
                return_value=2,
            ):
                result = await token_service.authorize_adhoc_token(
                    parties, mock_session, {}, "ADHOC"
                )

                assert result is not None
                assert result["allowed"] == AuthorizationEnum.ALLOWED
                assert result["responding_party"] == "DE*HUB"

                assert task_states.get("OWN") == "completed"

    @pytest.mark.django_db
    async def test_authorize_adhoc_token_returns_none_when_timeout_occurs(
        self, mock_session, mock_party_details, token_service, hubject_credentials
    ):
        p0 = mock_party_details(rank=0, pid="SLO", delay=0.3, allowed=True)
        parties = [p0]

        async def side_effect(session, url, **kwargs):
            await asyncio.sleep(0.3)
            return (200, {"data": {"allowed": "ALLOWED", "token": {"uid": "t"}}}, None)

        with patch.object(TokenAuthorizationService, "TIMEOUT", 0.1):
            with patch(
                "ocpi22.tokens.token_async.post_request", side_effect=side_effect
            ):
                with patch(
                    "ocpi22.credentials.services.CredentialsService.get_hubject_priority_rank",
                    return_value=2,
                ):
                    result = await token_service.authorize_adhoc_token(
                        parties, mock_session, {}, "ADHOC"
                    )
                    assert result is None

    @pytest.mark.django_db
    async def test_authorize_adhoc_token_executes_hubject_task(
        self, mock_session, mock_party_details, token_service, hubject_credentials
    ):
        p9 = mock_party_details(rank=9, pid="OTH", delay=0.1, allowed=False)
        parties = [p9]

        with patch("django.conf.settings.ENABLE_HUBJECT", True):
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
                        "ocpi22.credentials.services.CredentialsService.get_hubject_priority_rank",
                        return_value=2,
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

    def test_check_winner_among_candidates_returns_none_when_candidates_is_empty(
        self, token_service
    ):
        task_pending = MagicMock(spec=asyncio.Task)

        tasks_map = {task_pending: 0}
        pending = {task_pending}

        result = token_service._check_winner_among_candidates({}, tasks_map, pending)
        assert result is None

    def test_check_winner_among_candidates_returns_none_when_tasks_with_better_ranks_pending(
        self, token_service
    ):
        task_pending = MagicMock(spec=asyncio.Task)

        tasks_map = {task_pending: 0}
        pending = {task_pending}

        candidates = {2: {"allowed": AuthorizationEnum.ALLOWED}}

        result = token_service._check_winner_among_candidates(
            candidates, tasks_map, pending
        )
        assert result is None

    def test_check_winner_among_candidates_returns_winner_when_no_tasks_with_better_ranks_pending(
        self, token_service
    ):
        task_pending = MagicMock(spec=asyncio.Task)
        tasks_map = {task_pending: 5}
        pending = {task_pending}

        candidates = {2: {"allowed": AuthorizationEnum.ALLOWED}}

        result = token_service._check_winner_among_candidates(
            candidates, tasks_map, pending
        )
        assert result == candidates[2]
        task_pending.cancel.assert_called_once()

    @patch("ocpi22.tokens.token_async.process_task_result")
    def test_process_completed_task_returns_successful_response(
        self, mock_process, token_service
    ):
        candidates = {}
        first_denial = None

        mock_process.return_value = {"allowed": AuthorizationEnum.ALLOWED}

        task = MagicMock(spec=asyncio.Task)
        other_task = MagicMock(spec=asyncio.Task)
        pending = {other_task}
        tasks_map = {task: 2, other_task: 5}

        res, denial = token_service._process_completed_task(
            task, tasks_map, candidates, first_denial, pending
        )

        assert res == mock_process.return_value
        assert 2 in candidates
        other_task.cancel.assert_called_once()


@pytest.mark.asyncio
class TestKnownTokenAuthorization:
    async def test_return_allowed_response(
        self, mock_session, mock_party_details, token_service
    ):
        party = mock_party_details(rank=0, pid="OWN", allowed=True)
        unified_token_id = "TOKEN1"
        data = {"test": "data"}

        with patch(
            "ocpi22.tokens.token_async.post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = (
                200,
                {"data": {"allowed": AuthorizationEnum.ALLOWED, "token": {"uid": "t"}}},
                party["ocpi_master"],
            )

            result = await token_service.authorize_known_token(
                [party], mock_session, data, unified_token_id
            )

            assert result is not None
            assert result["allowed"] == AuthorizationEnum.ALLOWED
            mock_post.assert_called_once()
            assert mock_post.call_args[1]["url"] == party["url"]

    async def test_return_not_allowed_response(
        self, mock_session, mock_party_details, token_service
    ):
        party = mock_party_details(rank=0, pid="OWN", allowed=False)

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
                party["ocpi_master"],
            )

            result = await token_service.authorize_known_token(
                [party], mock_session, {}, "T1"
            )
            assert result is not None
            assert result["allowed"] == AuthorizationEnum.NOT_ALLOWED
