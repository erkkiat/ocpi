import pytest
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
