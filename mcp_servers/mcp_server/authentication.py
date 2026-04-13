"""
MCP Server Authentication

This module handles API key authentication following the implementation principles:
- Use custom DRF authentication class inheriting from BaseAuthentication
- Support both Authorization: Bearer <key> and X-API-Key: <key> headers
- Query ApiKey.objects.select_related("user") for efficiency
- Check is_active flag on API key
- Update last_used timestamp on successful authentication
- Raise AuthenticationFailed for invalid/inactive keys
"""

from django.contrib.auth import get_user_model
from rest_framework import authentication
from rest_framework import exceptions

from .models import ApiKey


User = get_user_model()


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Authentication using API keys for MCP clients"""

    def authenticate(self, request):
        """
        Authenticate the request using an API key.

        Expected header format:
        Authorization: Bearer <api_key>
        or
        X-API-Key: <api_key>
        """
        # Try Authorization header first
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:].strip()
        else:
            # Try X-API-Key header
            api_key = request.META.get("HTTP_X_API_KEY", "")

        if not api_key:
            return None

        try:
            api_key_obj = ApiKey.objects.select_related("user").get(
                key=api_key, is_active=True
            )
        except ApiKey.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid API key")

        # Update last used timestamp
        api_key_obj.update_last_used()

        # Return (user, auth) tuple
        return (api_key_obj.user, api_key_obj)
