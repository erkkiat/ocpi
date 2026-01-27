from unittest.mock import Mock, patch, ANY

import pytest
from django.core.cache import cache

from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.tests.factories import LocationFactory, TokenFactory, CredentialsRoleFactory
from ocpi22.tokens.auth import _authorize_token, authorize_token, TokenAuthorization
from ocpi22.models.location import Location
from ocpi22.models.token import Token
from ocpi22.choices import AuthorizationEnum, TokenType
from ocpiconnector.party import Party


class TestEvseIdAuthorizationCacheFix:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        cache.clear()

    @patch("ocpi22.tokens.auth.authorize_with_msps_sync")
    @patch("ocpi22.tokens.auth.find_route")
    @patch("util.redis_store")
    @pytest.mark.django_db
    def test_authorize_token_different_evse_ids_create_separate_msp_calls(
        self, mock_redis, mock_find_route, mock_authorize_with_msps
    ):
        mock_redis.get.side_effect = KeyError("Cache miss")

        token = TokenFactory(
            uid="TOKEN123",
            ocpi_master=CredentialsRoleFactory(country_code="DE", party_id="ABC"),
            valid=True,
            whitelist=Token.NEVER,
        )

        mock_route = Mock()
        mock_route.url = "https://msp.example.com/api"
        mock_route.token_base64 = "token123"
        mock_route.to.country_code = "DE"
        mock_route.to.party_id = "ABC"
        mock_route.credentials = Mock()
        mock_find_route.return_value = mock_route

        authorization_responses = [
            TokenAuthorization(
                allowed=AuthorizationEnum.ALLOWED,
                token={"uid": "TOKEN123"},
                authorization_reference="AUTH_REF_EVSE_001_123",
                auth_method="AUTH_REQUEST",
                billed_to="DE*ABC",
            ),
            TokenAuthorization(
                allowed=AuthorizationEnum.ALLOWED,
                token={"uid": "TOKEN123"},
                authorization_reference="AUTH_REF_EVSE_002_456",
                auth_method="AUTH_REQUEST",
                billed_to="DE*ABC",
            ),
        ]
        mock_authorize_with_msps.side_effect = authorization_responses

        mock_location = LocationFactory()

        first_evse_auth_result = _authorize_token(
            token, mock_location, evse_id="DE*ABC*E001"
        )

        second_evse_auth_result = _authorize_token(
            token, mock_location, evse_id="DE*ABC*E002"
        )

        assert mock_authorize_with_msps.call_count == 2
        assert first_evse_auth_result.authorization_reference == "AUTH_REF_EVSE_001_123"
        assert (
            second_evse_auth_result.authorization_reference == "AUTH_REF_EVSE_002_456"
        )
        assert (
            first_evse_auth_result.authorization_reference
            != second_evse_auth_result.authorization_reference
        )

    @patch("ocpi22.tokens.auth.authorize_with_msps_sync")
    @patch("ocpi22.tokens.auth.find_route")
    @patch("util.redis_store")
    @pytest.mark.django_db
    def test_authorize_token_same_evse_id_uses_cache(
        self, mock_redis, mock_find_route, mock_authorize_with_msps
    ):
        token = TokenFactory(
            uid="TOKEN123",
            ocpi_master=CredentialsRoleFactory(country_code="DE", party_id="ABC"),
            valid=True,
            whitelist=Token.NEVER,
        )

        mock_route = Mock()
        mock_route.url = "https://msp.example.com/api"
        mock_route.token_base64 = "token123"
        mock_route.to.country_code = "DE"
        mock_route.to.party_id = "ABC"
        mock_route.credentials = Mock()
        mock_find_route.return_value = mock_route

        mock_auth_response = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token={"uid": "TOKEN123"},
            authorization_reference="AUTH_REF_CACHED_123",
            auth_method="AUTH_REQUEST",
            billed_to="DE*ABC",
        )
        mock_authorize_with_msps.return_value = mock_auth_response

        mock_location = Mock(spec=Location)

        first_call_cache_miss = True

        def redis_get_side_effect(key):
            nonlocal first_call_cache_miss
            if first_call_cache_miss:
                first_call_cache_miss = False
                raise KeyError("Cache miss")
            else:
                import pickle

                return pickle.dumps(mock_auth_response)

        mock_redis.get.side_effect = redis_get_side_effect

        first_auth_attempt = _authorize_token(
            token, mock_location, evse_id="DE*ABC*E001"
        )

        cached_auth_attempt = _authorize_token(
            token, mock_location, evse_id="DE*ABC*E001"
        )

        assert mock_authorize_with_msps.call_count == 1
        assert first_auth_attempt.authorization_reference == "AUTH_REF_CACHED_123"
        assert cached_auth_attempt.authorization_reference == "AUTH_REF_CACHED_123"
        assert (
            first_auth_attempt.authorization_reference
            == cached_auth_attempt.authorization_reference
        )

    def test_cache_key_generation_includes_evse_id(self):
        from util import DistributedCache

        cache_decorator = DistributedCache()

        evse_001_cache_key = cache_decorator.generate_cache_key(
            _authorize_token, ("TOKEN123", "mock_location"), {"evse_id": "DE*ABC*E001"}
        )

        evse_002_cache_key = cache_decorator.generate_cache_key(
            _authorize_token, ("TOKEN123", "mock_location"), {"evse_id": "DE*ABC*E002"}
        )

        assert evse_001_cache_key != evse_002_cache_key

        evse_001_cache_key_duplicate = cache_decorator.generate_cache_key(
            _authorize_token, ("TOKEN123", "mock_location"), {"evse_id": "DE*ABC*E001"}
        )

        assert evse_001_cache_key == evse_001_cache_key_duplicate

    def test_authorize_token_function_accepts_evse_id_parameter(self):
        import inspect

        authorize_token_signature = inspect.signature(authorize_token)
        assert "evse_id" in authorize_token_signature.parameters
        assert authorize_token_signature.parameters["evse_id"].default is None

        private_authorize_token_signature = inspect.signature(_authorize_token)
        assert "evse_id" in private_authorize_token_signature.parameters
        assert private_authorize_token_signature.parameters["evse_id"].default is None

    @patch("ocpi22.tokens.auth.authorize_with_msps_sync")
    @patch("ocpi22.tokens.auth.Token.get_if_exists")
    @patch("util.redis_store")
    @pytest.mark.django_db
    def test_authorize_token_passes_through_evse_id_for_unknown_tokens(
        self, mock_redis, mock_token_get, mock_authorize_with_msps
    ):
        mock_redis.get.side_effect = KeyError("Cache miss")
        mock_token_get.return_value = None

        mock_location = Mock(spec=Location)

        unknown_token_mock_response = TokenAuthorization(
            allowed=AuthorizationEnum.ALLOWED,
            token=AdhocToken(
                Party(), "UNKNOWN_TOKEN", TokenType.AD_HOC_USER.value, None
            ),
            authorization_reference="AUTH_REF_UNKNOWN_123",
            auth_method="AUTH_REQUEST",
            billed_to="DE*ABC",
        )
        mock_authorize_with_msps.return_value = unknown_token_mock_response

        unknown_token_auth_result = _authorize_token(
            "UNKNOWN_TOKEN", mock_location, evse_id="DE*ABC*E001"
        )

        mock_authorize_with_msps.assert_called_once_with(
            "UNKNOWN_TOKEN", ANY, mock_location
        )
        assert (
            unknown_token_auth_result.authorization_reference == "AUTH_REF_UNKNOWN_123"
        )
