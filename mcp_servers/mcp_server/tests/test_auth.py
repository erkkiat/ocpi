"""
MCP Server Authentication Tests

This module tests API key authentication following the implementation principles:
- Use @pytest.mark.django_db decorator for database tests
- Test both success and error cases
- Test authentication flows (valid key, invalid key, inactive key, missing key)
- Never mock Django model operations - use real implementations
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory
from rest_framework.exceptions import AuthenticationFailed

from mcp_servers.mcp_server.models import ApiKey
from mcp_servers.mcp_server.authentication import ApiKeyAuthentication

User = get_user_model()


@pytest.mark.django_db
class TestApiKeyAuthentication:
    """Test API key authentication"""

    def test_api_key_generation(self):
        """Test that API keys are generated automatically"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        assert api_key.key is not None
        assert len(api_key.key) == 64
        assert api_key.is_active is True

    def test_api_key_authentication_with_bearer_header(self):
        """Test authentication with Bearer token in Authorization header"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        factory = APIRequestFactory()
        request = factory.get("/", HTTP_AUTHORIZATION=f"Bearer {api_key.key}")

        auth = ApiKeyAuthentication()
        result = auth.authenticate(request)

        assert result is not None
        authenticated_user, auth_obj = result
        assert authenticated_user == user
        assert auth_obj == api_key

    def test_api_key_authentication_with_x_api_key_header(self):
        """Test authentication with X-API-Key header"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        factory = APIRequestFactory()
        request = factory.get("/", HTTP_X_API_KEY=api_key.key)

        auth = ApiKeyAuthentication()
        result = auth.authenticate(request)

        assert result is not None
        authenticated_user, auth_obj = result
        assert authenticated_user == user
        assert auth_obj == api_key

    def test_api_key_authentication_invalid_key(self):
        """Test that invalid API key raises AuthenticationFailed"""
        factory = APIRequestFactory()
        request = factory.get("/", HTTP_AUTHORIZATION="Bearer invalid_key")

        auth = ApiKeyAuthentication()

        with pytest.raises(AuthenticationFailed):
            auth.authenticate(request)

    def test_api_key_authentication_inactive_key(self):
        """Test that inactive API key raises AuthenticationFailed"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key", is_active=False)

        factory = APIRequestFactory()
        request = factory.get("/", HTTP_AUTHORIZATION=f"Bearer {api_key.key}")

        auth = ApiKeyAuthentication()

        with pytest.raises(AuthenticationFailed):
            auth.authenticate(request)

    def test_api_key_authentication_no_key(self):
        """Test that missing API key returns None"""
        factory = APIRequestFactory()
        request = factory.get("/")

        auth = ApiKeyAuthentication()
        result = auth.authenticate(request)

        assert result is None

    def test_api_key_update_last_used(self):
        """Test that last_used timestamp is updated on authentication"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        # Initially last_used should be None
        assert api_key.last_used is None

        factory = APIRequestFactory()
        request = factory.get("/", HTTP_AUTHORIZATION=f"Bearer {api_key.key}")

        auth = ApiKeyAuthentication()
        auth.authenticate(request)

        # Refresh from database
        api_key.refresh_from_db()
        assert api_key.last_used is not None

    def test_api_key_unique_constraint(self):
        """Test that API keys must be unique"""
        user = User.objects.create_user(username="testuser", password="testpass")

        # Create first API key
        api_key1 = ApiKey.objects.create(user=user, name="Test Key 1")

        # Try to create second API key with same key (should fail)
        with pytest.raises(Exception):  # IntegrityError
            api_key2 = ApiKey(user=user, name="Test Key 2", key=api_key1.key)
            api_key2.save()

    def test_api_key_str_representation(self):
        """Test that ApiKey string representation is correct"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        assert str(api_key) == "Test Key (testuser)"

    def test_api_key_update_last_used_method(self):
        """Test the update_last_used method directly"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        # Initially last_used should be None
        assert api_key.last_used is None

        # Call update_last_used directly
        api_key.update_last_used()

        # Refresh from database
        api_key.refresh_from_db()
        assert api_key.last_used is not None
