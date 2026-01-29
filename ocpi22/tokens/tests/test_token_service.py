import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from django.test import override_settings

from ocpi22.tokens.dataclasses import PartyDetails
from ocpi22.tokens.services import TokenAuthorizationService
from ocpi22.tokens.token_async import AuthorizationEnum, process_task_result
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

@pytest.fixture
def session():
    return OCPISessionFactory()


class TestAdhocTokenAuthorization:
    def _create_delayed_post_request(self, parties, task_states=None):
        async def delayed_post_request(session, url, data, ocpi_master, **kwargs):
            party = next(party for party in parties if party["party_details"].url == url)
            party_details = party["party_details"]

            try:
                await asyncio.sleep(party["_delay"])
                if task_states is not None:
                    task_states[f"{party_details.country_code}*{party_details.party_id}"] = "completed"

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
            except asyncio.CancelledError:
                if task_states is not None:
                    task_states[party["party_details"].party_id] = "cancelled"
                raise
        return delayed_post_request

    @pytest.mark.django_db
    async def test_ranking_priority_when_more_than_one_party_returns_allowed(
        self, party_details, token_service, hubject_credentials, location, session
    ):
        # Lowest value is the highest priority
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
        self, party_details, token_service, hubject_credentials, location, session
    ):
        msp_fr_111 = await sync_to_async(party_details)(priority=2, country_code="FR", party_id="111", allowed=False)
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
            assert result["responding_party"] == "FI*MSP"

    @pytest.mark.django_db
    async def test_waiting_for_higher_ranked_party_when_lower_ranked_party_returns_allowed_fast(
        self, party_details, token_service, hubject_credentials, location, session
    ):
        msp_de_hub = await sync_to_async(party_details)(
            priority=2, country_code="DE", party_id="HUB", delay=0.2, allowed=True)
        msp_fr_111 = await sync_to_async(party_details)(
            priority=4, country_code="FR", party_id="111", delay=0, allowed=True
        )
        parties = [msp_de_hub, msp_fr_111]
        task_states = {}

        delayed_post_request = self._create_delayed_post_request(parties, task_states)
        parties_details = [party["party_details"] for party in parties]

        with patch("ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request):
            result = await token_service.authorize_adhoc_token(
                parties_details, session, {"location_id": location.uid}, "ADHOC"
            )

            assert result is not None
            assert result["allowed"] == AuthorizationEnum.ALLOWED
            assert result["responding_party"] == "DE*HUB"

            assert task_states.get("DE*HUB") == "completed"

    @pytest.mark.django_db
    async def test_authorize_adhoc_token_handles_task_timeout_exception(
        self, party_details, token_service, hubject_credentials, location, session
    ):
        msp_fr_111 = await sync_to_async(party_details)(
            priority=2, country_code="FR", party_id="111", delay=0.5, allowed=True
        )
        parties_details = [msp_fr_111["party_details"]]
        parties = [msp_fr_111]

        token_service._timeout = 0.1
        delayed_post_request = self._create_delayed_post_request(parties)

        with patch("ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request):
            result = await token_service.authorize_adhoc_token(
                parties_details, session, {}, "ADHOC"
            )
            assert result is None

    @pytest.mark.django_db
    async def test_authorize_adhoc_token_returns_none_when_timeout_occurs(
        self, party_details, token_service, hubject_credentials, location, session
    ):

        msp_fr_111 = await sync_to_async(party_details)(
            priority=2, country_code="FR", party_id="111", delay=0.3, allowed=True
        )
        parties = [msp_fr_111]

        token_service._timeout = 0.1
        
        delayed_post_request = self._create_delayed_post_request(parties)
        parties_details = [party["party_details"] for party in parties]

        with patch("ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request):
            result = await token_service.authorize_adhoc_token(
                parties_details, session, {}, "ADHOC"
            )
            assert result is None

    @pytest.mark.django_db(transaction=True)
    @override_settings(ENABLE_HUBJECT=True)
    async def test_authorize_adhoc_token_executes_hubject_task(
        self, party_details, token_service, location, session, hubject_credentials
    ):

        msp_fr_111 = await sync_to_async(party_details)(
            priority=9, country_code="FR", party_id="111", allowed=False
        )
        parties = [msp_fr_111]
        parties_details = [party["party_details"] for party in parties]
        delayed_post_request = self._create_delayed_post_request(parties)

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
                "ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request
            ):
                result = await token_service.authorize_adhoc_token(
                    parties_details, session, {"location_id": location.uid}, "ADHOC"
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
    @pytest.mark.django_db
    async def test_return_allowed_response(
        self, party_details, token_service, location, session
    ):
        msp_fr_111 = await sync_to_async(party_details)(
            priority=2, country_code="FR", party_id="111", allowed=True
        )

        with patch(
            "ocpi22.tokens.token_async.post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = (
                200,
                {"data": {"allowed": AuthorizationEnum.ALLOWED, "token": {"uid": "t"}}},
                msp_fr_111["party_details"].ocpi_master,
            )

            result = await token_service.authorize_known_token(
                [msp_fr_111["party_details"]], session,
                {"location_id": location.uid}, "t"
            )

            assert result is not None
            assert result["allowed"] == AuthorizationEnum.ALLOWED
            mock_post.assert_called_once()
            assert mock_post.call_args[1]["url"] == msp_fr_111["party_details"].url

    @pytest.mark.django_db
    async def test_return_not_allowed_response(
        self, party_details, token_service, location, session
    ):
        msp_fr_111 = await sync_to_async(party_details)(
            priority=2, country_code="FR", party_id="111", allowed=False
        )

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
                msp_fr_111["party_details"].ocpi_master,
            )

            result = await token_service.authorize_known_token(
                [msp_fr_111["party_details"]], session, {}, "t"
            )
            assert result is not None
            assert result["allowed"] == AuthorizationEnum.NOT_ALLOWED


class TestProcessTaskResult:
    def test_process_task_result_handles_timeout_exception(self):
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.result.side_effect = asyncio.TimeoutError("Task timed out")

        result = process_task_result(mock_task)

        assert result is None

    def test_process_task_result_returns_none_when_status_code_is_not_200(self):
        mock_task = MagicMock(spec=asyncio.Task)
        allowed_response = {
            "data": {
                "allowed": "ALLOWED",
                "token": {
                    "country_code": "DE",
                    "party_id": "MSP"
                }
            }
        }
        mock_task.result.return_value = (400, {"data": allowed_response}, "OCPI_MASTER")
        mock_task.get_name.return_value = "DE*MSP"

        result = process_task_result(mock_task)

        assert result is None

    def test_process_task_result_returns_json_data_when_auth_request_is_allowed(self):
        mock_task = MagicMock(spec=asyncio.Task)

        allowed_response = {
            "data": {
                "allowed": "ALLOWED",
                "token": {
                    "country_code": "DE",
                    "party_id": "MSP"
                }
            }
        }
        mock_task.result.return_value = (200, allowed_response, "DE*MSP")
        mock_task.get_name.return_value = "DE*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "ALLOWED"

    def test_process_task_result_returns_json_data_when_auth_request_is_not_allowed(self):
        mock_task = MagicMock(spec=asyncio.Task)

        not_allowed_response = {
            "data": {
                "allowed": "NOT_ALLOWED",
                "token": {
                    "country_code": "DE",
                    "party_id": "MSP"
                }
            }
        }
        mock_task.result.return_value = (200, not_allowed_response, "DE*MSP")
        mock_task.get_name.return_value = "DE*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "NOT_ALLOWED"


