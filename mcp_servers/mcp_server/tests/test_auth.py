"""
MCP Server Model Tests

This module tests the ApiKey model following the implementation principles:
- Use @pytest.mark.django_db decorator for database tests
- Test both success and error cases
- Never mock Django model operations - use real implementations
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from mcp_servers.mcp_server.models import ApiKey

User = get_user_model()


@pytest.mark.django_db
class TestApiKeyModel:
    """Test ApiKey model"""

    def test_api_key_generation(self):
        """Test that API keys are generated automatically"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        assert api_key.key is not None
        assert len(api_key.key) == 64
        assert api_key.is_active is True

    def test_api_key_update_last_used(self):
        """Test that last_used timestamp can be updated"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key = ApiKey.objects.create(user=user, name="Test Key")

        # Initially last_used should be None
        assert api_key.last_used is None

        # Update last_used
        api_key.update_last_used()

        # Refresh from database
        api_key.refresh_from_db()
        assert api_key.last_used is not None

    def test_api_key_unique_constraint(self):
        """Test that API keys must be unique"""
        user = User.objects.create_user(username="testuser", password="testpass")

        # Create first API key
        api_key1 = ApiKey.objects.create(user=user, name="Test Key 1")

        # Try to create second API key with same key (should fail)
        with pytest.raises(IntegrityError):
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
        
    def test_api_key_ordering(self):
        """Test that API keys are ordered by created_at descending"""
        user = User.objects.create_user(username="testuser", password="testpass")
        api_key1 = ApiKey.objects.create(user=user, name="Test Key 1")
        api_key2 = ApiKey.objects.create(user=user, name="Test Key 2")

        keys = list(ApiKey.objects.all())
        assert keys[0] == api_key2
        assert keys[1] == api_key1
