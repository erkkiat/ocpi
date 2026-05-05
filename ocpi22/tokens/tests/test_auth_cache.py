import pytest

from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.routing import find_route
from ocpi22.tests.factories import (
    CredentialsRoleFactory,
    OCPISessionFactory,
    TokenFactory,
)
from ocpi22.tokens.auth import _authorize_token, session_post_save
from ocpi22.tokens.dataclasses import TokenDto


@pytest.fixture(autouse=True)
def clear_caches():
    _authorize_token.cache_clear()
    find_route.cache_clear()


@pytest.fixture
def always_whitelist_token():
    return TokenFactory(
        uid="ALWAYS_TOKEN",
        whitelist=Token.ALWAYS,
        ocpi_master=CredentialsRoleFactory(
            country_code="DE", party_id="TST", role="EMSP"
        ),
    )


@pytest.fixture
def always_token_dto(always_whitelist_token):
    return TokenDto(
        uid=always_whitelist_token.uid, adhoc=False, token=always_whitelist_token
    )


@pytest.mark.django_db
class TestSessionPostSaveClearsAuthorizeTokenCache:
    def test_session_post_save_when_status_set_to_completed_clears_authorize_token_cache(
        self, always_token_dto
    ):
        _authorize_token(always_token_dto)
        _authorize_token(always_token_dto)
        assert _authorize_token.cache_info().hits == 1

        session = OCPISessionFactory(status=Session.ACTIVE)
        session.status = Session.COMPLETED
        session.save(update_fields=["status"])

        assert _authorize_token.cache_info().hits == 0
        assert _authorize_token.cache_info().misses == 0

    @pytest.mark.parametrize("status", [Session.ACTIVE, Session.PENDING])
    def test_session_post_save_when_status_not_completed_does_not_clear_authorize_token_cache(
        self, status, always_token_dto
    ):
        _authorize_token(always_token_dto)
        _authorize_token(always_token_dto)
        assert _authorize_token.cache_info().hits == 1

        session = OCPISessionFactory(status=Session.ACTIVE)
        session.status = status
        session.save(update_fields=["status"])

        assert _authorize_token.cache_info().hits == 1

    def test_session_post_save_when_raw_is_true_does_not_clear_authorize_token_cache(
        self, always_token_dto
    ):
        _authorize_token(always_token_dto)
        _authorize_token(always_token_dto)
        assert _authorize_token.cache_info().hits == 1

        session = OCPISessionFactory(status=Session.ACTIVE)
        session.status = Session.COMPLETED
        session_post_save(Session, session, raw=True)

        assert _authorize_token.cache_info().hits == 1
