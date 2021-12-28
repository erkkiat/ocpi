import base64
import binascii

from rest_framework import exceptions
from rest_framework.permissions import DjangoModelPermissions
from rest_framework.reverse import reverse

from ocpi22.models import Credentials


class OCPI_AUTH_TYPES:
    NONE=0
    TOKEN_A=1
    FINAL=2


def check_auth_token(request, token):
    # Only certain endpoints can be accessed using TOKEN_A during the credentials exchange
    allowed_for_token_a = (
        reverse('base-versions'),       # The "Versions" endpoint
        reverse('credentials-list'),    # Getting the Credentials
        reverse('ocpi-22')              # The "Endpoints" endpoint
    )
    try:
        token_ascii = base64.b64decode(token).decode('ascii')
        request.ocpi_auth = OCPI_AUTH_TYPES.NONE

        # First check for TOKEN_A, are we still getting to know each other?
        # noinspection PyUnresolvedReferences
        credentials_matches = Credentials.objects.filter(token_a=token_ascii)
        if credentials_matches.count():
            if request.path not in allowed_for_token_a:
                raise exceptions.NotAuthenticated(
                    f'TOKEN_A can only be used for the Credentials and Versions modules, not for path "{request.path}".'
                )

            # Don't accept TOKEN_A anymore, if tokens have been exchanged
            # NOTE: At a given time, one party may possess all three tokens while the other has only two

            credentials = credentials_matches[0]
            if credentials.ours and credentials.theirs:
                raise exceptions.NotAuthenticated(f'TOKEN_A has expired when TOKEN_B and TOKEN_C were exchanged')

            request.ocpi_auth = OCPI_AUTH_TYPES.TOKEN_A
            request.credentials = credentials
            return True
        else:
            # Or are we already friends?
            # noinspection PyUnresolvedReferences
            credentials_matches = Credentials.objects.filter(ours=token_ascii)
            if credentials_matches.count():
                credentials = credentials_matches[0]
                request.ocpi_auth = OCPI_AUTH_TYPES.FINAL
                request.credentials = credentials
                return True
    except (binascii.Error, UnicodeDecodeError) as e:
        raise exceptions.NotAuthenticated(f'Authentication token: {e}')
    if token:
        # This token is no good
        raise exceptions.NotAuthenticated(f'The token "{token}" doesn\'t match any of our current credentials')
    # If no token, give other permission mechanisms a chance
    return False


class OCPIPermission(DjangoModelPermissions):
    """
    Check for valid OCPI authentication header and secondarily basic auth with local user IDs
    """

    def has_permission(self, request, view):
        # Get the OCPI Authorization header or if none, the auth-test query param
        # Remove the "Token" keyword if present to get just the token value
        auth_id = request.META.get('HTTP_AUTHORIZATION',
                                   request.GET.get('auth-test', '')).replace('Token ', '')
        # Check for token authentication, secondarily basic auth
        if check_auth_token(request, auth_id) or \
            hasattr(view, 'publicly_visible') or \
            super().has_permission(request, view):
                return True
        raise exceptions.NotAuthenticated
