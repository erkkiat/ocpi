import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from django.test import override_settings

from ocpi22.tokens.dataclasses import PartyDetails, TokenDto
from ocpi22.tokens.services import TokenAuthorizationService
from ocpi22.tokens.token_async import (
    AuthorizationEnum,
    process_task_result,
    authorize_with_msps_sync,
)
from ocpi22.tests.factories import (
    CredentialsRoleFactory,
    CredentialsFactory,
    OCPISessionFactory,
    LocationFactory,
    EvseFactory,
)
from ocpi22.choices import OcpiRolesEnum
from asgiref.sync import sync_to_async


@pytest.fixture
def location():
    location = LocationFactory(
        uid="LOC1",
    )
    EvseFactory(
        location=location,
        uid="EVSE1",
    )
    return location


@pytest.fixture
def party_details(location):
    def _create_party_details(
        priority, country_code, party_id, delay=0, allowed=True, hub=False
    ):
        credentials = CredentialsFactory(
            auth_priority=priority, allowed_locations=[location.uid]
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
            party = next(
                party for party in parties if party["party_details"].url == url
            )
            party_details = party["party_details"]

            try:
                await asyncio.sleep(party["_delay"])
                if task_states is not None:
                    task_states[
                        f"{party_details.country_code}*{party_details.party_id}"
                    ] = "completed"

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
        msp_fr_111 = await sync_to_async(party_details)(
            priority=2, country_code="FR", party_id="111", allowed=True
        )
        msp_fi_msp = await sync_to_async(party_details)(
            priority=3, country_code="FI", party_id="MSP", allowed=True
        )
        parties = [msp_fr_111, msp_fi_msp]

        delayed_post_request = self._create_delayed_post_request(parties)

        parties_details = [party["party_details"] for party in parties]

        with patch(
            "ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request
        ):
            result = await token_service.authorize_adhoc_token(
                parties_details, {"location_id": location.uid}, "ADHOC"
            )

            assert result is not None
            assert result["allowed"] == AuthorizationEnum.ALLOWED
            assert result["responding_party"] == "FR*111"

    @pytest.mark.django_db
    async def test_ranking_priority_when_party_returns_allowed_and_other_party_returns_not_allowed(
        self, party_details, token_service, hubject_credentials, location, session
    ):
        msp_fr_111 = await sync_to_async(party_details)(
            priority=2, country_code="FR", party_id="111", allowed=False
        )
        msp_fi_msp = await sync_to_async(party_details)(
            priority=3, country_code="FI", party_id="MSP", allowed=True
        )
        parties = [msp_fr_111, msp_fi_msp]

        delayed_post_request = self._create_delayed_post_request(parties)
        parties_details = [party["party_details"] for party in parties]

        with patch(
            "ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request
        ):
            result = await token_service.authorize_adhoc_token(
                parties_details, {"location_id": location.uid}, "ADHOC"
            )

            assert result is not None
            assert result["allowed"] == AuthorizationEnum.ALLOWED
            assert result["responding_party"] == "FI*MSP"

    @pytest.mark.django_db
    async def test_waiting_for_higher_ranked_party_when_lower_ranked_party_returns_allowed_fast(
        self, party_details, token_service, hubject_credentials, location, session
    ):
        msp_de_hub = await sync_to_async(party_details)(
            priority=2, country_code="DE", party_id="HUB", delay=0.2, allowed=True
        )
        msp_fr_111 = await sync_to_async(party_details)(
            priority=4, country_code="FR", party_id="111", delay=0, allowed=True
        )
        parties = [msp_de_hub, msp_fr_111]
        task_states = {}

        delayed_post_request = self._create_delayed_post_request(parties, task_states)
        parties_details = [party["party_details"] for party in parties]

        with patch(
            "ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request
        ):
            result = await token_service.authorize_adhoc_token(
                parties_details, {"location_id": location.uid}, "ADHOC"
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

        with patch(
            "ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request
        ):
            result = await token_service.authorize_adhoc_token(
                parties_details, {}, "ADHOC"
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

        with patch(
            "ocpi22.tokens.token_async.post_request", side_effect=delayed_post_request
        ):
            result = await token_service.authorize_adhoc_token(
                parties_details, {}, "ADHOC"
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
                "ocpi22.tokens.token_async.post_request",
                side_effect=delayed_post_request,
            ):
                result = await token_service.authorize_adhoc_token(
                    parties_details, {"location_id": location.uid}, "ADHOC"
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
                [msp_fr_111["party_details"]],
                {"location_id": location.uid},
                "t",
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
                [msp_fr_111["party_details"]], {}, "t"
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
                "token": {"country_code": "DE", "party_id": "MSP"},
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
                "token": {"country_code": "DE", "party_id": "MSP"},
            }
        }
        mock_task.result.return_value = (200, allowed_response, "DE*MSP")
        mock_task.get_name.return_value = "DE*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "ALLOWED"

    def test_process_task_result_returns_json_data_when_auth_request_is_not_allowed(
        self,
    ):
        mock_task = MagicMock(spec=asyncio.Task)

        not_allowed_response = {
            "data": {
                "allowed": "NOT_ALLOWED",
                "token": {"country_code": "DE", "party_id": "MSP"},
            }
        }
        mock_task.result.return_value = (200, not_allowed_response, "DE*MSP")
        mock_task.get_name.return_value = "DE*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "NOT_ALLOWED"

    def test_process_task_result_returns_not_allowed_when_response_has_custom_error(
        self, caplog
    ):
        mock_task = MagicMock(spec=asyncio.Task)

        error_response = {
            "status_code": 2000,
            "status_message": "Custom Error",
            "data": {},
        }
        mock_task.result.return_value = (200, error_response, "DE*MSP")
        mock_task.get_name.return_value = "DE*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "NOT_ALLOWED"
        assert "token" not in result
        assert "DE*MSP responded OCPI error Custom Error" in caplog.text

    def test_process_task_result_returns_none_when_response_data_empty_and_status_code_lt_2000(
        self,
    ):
        mock_task = MagicMock(spec=asyncio.Task)

        error_response = {
            "status_code": 1500,
            "status_message": "Success with no information on authorization",
            "data": {},
        }
        mock_task.result.return_value = (200, error_response, "DE*MSP")
        mock_task.get_name.return_value = "DE*MSP"

        result = process_task_result(mock_task)

        assert result is None


class TestProcessTaskResultOcpiErrorVariants:
    def test_process_task_result_returns_not_allowed_without_token_field_when_ocpi_error_2001(
        self, caplog
    ):
        mock_task = MagicMock(spec=asyncio.Task)
        error_response = {
            "status_code": 2001,
            "status_message": "Invalid or missing parameters",
            "data": {},
        }
        mock_task.result.return_value = (200, error_response, "FR*MSP")
        mock_task.get_name.return_value = "FR*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "NOT_ALLOWED"
        assert "token" not in result
        assert (
            "FR*MSP responded OCPI error Invalid or missing parameters" in caplog.text
        )

    def test_process_task_result_returns_not_allowed_without_token_field_when_ocpi_error_2919(
        self, caplog
    ):
        mock_task = MagicMock(spec=asyncio.Task)
        error_response = {
            "status_code": 2919,
            "status_message": "No valid contract",
            "data": {},
        }
        mock_task.result.return_value = (200, error_response, "NL*MSP")
        mock_task.get_name.return_value = "NL*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "NOT_ALLOWED"
        assert "token" not in result
        assert "NL*MSP responded OCPI error No valid contract" in caplog.text

    def test_process_task_result_returns_not_allowed_without_token_field_when_ocpi_error_3000(
        self, caplog
    ):
        mock_task = MagicMock(spec=asyncio.Task)
        error_response = {
            "status_code": 3000,
            "status_message": "Unknown Token",
            "data": {},
        }
        mock_task.result.return_value = (200, error_response, "BE*MSP")
        mock_task.get_name.return_value = "BE*MSP"

        result = process_task_result(mock_task)

        assert result is not None
        assert result.get("allowed") == "NOT_ALLOWED"
        assert "token" not in result
        assert "BE*MSP responded OCPI error Unknown Token" in caplog.text


class TestAuthorizeWithMspsSyncEarlyReturn:
    """Tests for authorize_with_msps_sync early return logic for NOT_ALLOWED responses"""

    @pytest.fixture
    def token_dto(self):
        return TokenDto(
            uid="TEST_TOKEN_123",
            adhoc=True,
            token=None,
        )

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_returns_token_not_authorized_when_response_is_none(
        self, token_dto, location
    ):
        parties = [
            (
                "http://test.com",
                "token_base64",
                "DE",
                "MSP",
                MagicMock(),
            )
        ]

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = None

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.NOT_ALLOWED
            assert result.token.uid == "TEST_TOKEN_123"
            assert result.token.valid is False

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_returns_token_not_authorized_when_ocpi_error_response(
        self, token_dto, location, caplog
    ):
        parties = [
            (
                "http://test.com",
                "token_base64",
                "FR",
                "MSP",
                MagicMock(),
            )
        ]

        ocpi_error_response = {
            "allowed": "NOT_ALLOWED",
            "responding_party": "FR*MSP",
        }

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = ocpi_error_response

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.NOT_ALLOWED
            assert result.token.uid == "TEST_TOKEN_123"
            assert result.token.valid is False
            assert "Token TEST_TOKEN_123 not authorized by FR*MSP" in caplog.text

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_returns_token_not_authorized_when_valid_denial_response(
        self, token_dto, location, caplog
    ):
        parties = [
            (
                "http://test.com",
                "token_base64",
                "NL",
                "MSP",
                MagicMock(),
            )
        ]

        valid_denial_response = {
            "allowed": "NOT_ALLOWED",
            "token": {
                "uid": "TEST_TOKEN_123",
                "type": "RFID",
                "valid": False,
                "country_code": "NL",
                "party_id": "MSP",
            },
            "responding_party": "NL*MSP",
            "msp": "NL*MSP",
        }

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = valid_denial_response

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.NOT_ALLOWED
            assert result.token.uid == "TEST_TOKEN_123"
            assert result.token.valid is False
            assert "Token TEST_TOKEN_123 not authorized by NL*MSP" in caplog.text

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_processes_allowed_response_through_serializer(
        self, token_dto, location
    ):
        parties = [
            (
                "http://test.com",
                "token_base64",
                "DE",
                "MSP",
                MagicMock(),
            )
        ]

        allowed_response = {
            "allowed": "ALLOWED",
            "token": {
                "uid": "TEST_TOKEN_123",
                "type": "RFID",
                "valid": True,
                "country_code": "DE",
                "party_id": "MSP",
            },
            "responding_party": "DE*MSP",
            "msp": "DE*MSP",
        }

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = allowed_response

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.ALLOWED
            assert result.token.uid == "TEST_TOKEN_123"
            assert result.token.valid is True
            assert result.responding_party == "DE*MSP"

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_returns_token_not_authorized_when_serializer_validation_fails(
        self, token_dto, location, caplog
    ):
        parties = [
            (
                "http://test.com",
                "token_base64",
                "BE",
                "MSP",
                MagicMock(),
            )
        ]

        malformed_allowed_response = {
            "allowed": "ALLOWED",
            "token": {
                "uid": "TEST_TOKEN_123",
            },
            "responding_party": "BE*MSP",
            "msp": "BE*MSP",
        }

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = malformed_allowed_response

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.NOT_ALLOWED
            assert (
                "Cannot create TokenAuthorization from ALLOWED response" in caplog.text
            )

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_handles_priority1_ocpi_error_priority2_allowed(
        self, token_dto, location
    ):
        parties = [
            ("http://priority1.com", "token1", "FR", "MSP1", MagicMock()),
            ("http://priority2.com", "token2", "DE", "MSP2", MagicMock()),
        ]

        allowed_response = {
            "allowed": "ALLOWED",
            "token": {
                "uid": "TEST_TOKEN_123",
                "type": "RFID",
                "valid": True,
                "country_code": "DE",
                "party_id": "MSP2",
            },
            "responding_party": "DE*MSP2",
            "msp": "DE*MSP2",
        }

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = allowed_response

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.ALLOWED
            assert result.responding_party == "DE*MSP2"

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_handles_all_msps_return_ocpi_errors(
        self, token_dto, location, caplog
    ):
        parties = [
            ("http://msp1.com", "token1", "FR", "MSP1", MagicMock()),
            ("http://msp2.com", "token2", "DE", "MSP2", MagicMock()),
        ]

        ocpi_error_response = {
            "allowed": "NOT_ALLOWED",
            "responding_party": "FR*MSP1",
        }

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = ocpi_error_response

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.NOT_ALLOWED
            assert "Token TEST_TOKEN_123 not authorized by FR*MSP1" in caplog.text

    @pytest.mark.django_db
    def test_authorize_with_msps_sync_handles_all_msps_timeout(
        self, token_dto, location
    ):
        parties = [
            ("http://msp1.com", "token1", "FR", "MSP1", MagicMock()),
        ]

        with patch(
            "ocpi22.tokens.token_async.authorize_with_msps",
            new_callable=AsyncMock,
        ) as mock_authorize:
            mock_authorize.return_value = None

            result = authorize_with_msps_sync(token_dto, parties, location)

            assert result is not None
            assert result.allowed == AuthorizationEnum.NOT_ALLOWED
            assert result.token.valid is False
