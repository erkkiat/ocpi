import base64
import binascii

from cachetools import cached
from django.utils.functional import cached_property
from rest_framework import exceptions
from rest_framework.permissions import DjangoModelPermissions
from rest_framework.reverse import reverse

from ocpi22.models.credentials import Credentials
from ocpiconnector.settings import PUBLIC_VIEWS


class OcpiAuthTypes:
    NONE = 0
    TOKEN_A = 1
    FINAL = 2


def check_auth_token(request, token: str) -> bool:
    @cached
    def allowed_for_token_a():
        return (
            reverse('base-versions'),  # The "Versions" endpoint
            reverse('credentials-list'),  # Getting the Credentials
            reverse('ocpi-22')  # The "Endpoints" endpoint
        )

    # Only certain endpoints can be accessed using TOKEN_A during the credentials exchange
    try:
        token_ascii = base64.b64decode(token).decode('ascii')
        request.ocpi_auth = OcpiAuthTypes.NONE

        # First check for TOKEN_A, are we still getting to know each other?
        # noinspection PyUnresolvedReferences
        credentials_matches = Credentials.objects.filter(token_a=token_ascii, valid=True)
        if credentials_matches.count():
            if request.path not in allowed_for_token_a():
                raise exceptions.NotAuthenticated(  # HTTP 401
                    f'TOKEN_A can only be used for the Credentials and Versions modules, not for path "{request.path}".'
                )

            # Don't accept TOKEN_A anymore, if tokens have been exchanged
            # NOTE: At a given time, one party may possess all three tokens while the other has only two

            credentials = credentials_matches[0]
            if credentials.is_complete():
                raise exceptions.NotAuthenticated(f'TOKEN_A has expired when the credentials exchange was completed')

            request.ocpi_auth = OcpiAuthTypes.TOKEN_A
            request.credentials = credentials
            return True
        else:
            # Or are we already friends?
            # noinspection PyUnresolvedReferences
            credentials_matches = Credentials.objects.filter(ours=token_ascii, valid=True)
            if credentials_matches.count():
                credentials = credentials_matches[0]
                request.ocpi_auth = OcpiAuthTypes.FINAL
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

    perms_map = {
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'OPTIONS': [],
        'HEAD': [],
        'POST': ['%(app_label)s.add_%(model_name)s'],
        'PUT': ['%(app_label)s.change_%(model_name)s'],
        'PATCH': ['%(app_label)s.change_%(model_name)s'],
        'DELETE': ['%(app_label)s.delete_%(model_name)s'],
    }

    @staticmethod
    def get_token(request) -> str:
        authorization = request.META.get('HTTP_AUTHORIZATION',
                                         request.META.get('Authorization',
                                                          request.GET.get('auth-test', '')))
        if authorization.startswith("Token "):
            return authorization[6:]
        return ''

    @cached_property
    def public_views(self):
        return [reverse(i) for i in PUBLIC_VIEWS]

    def has_permission(self, request, view=None):
        # Get the OCPI Authorization header or if none, the auth-test query param
        # Remove the "Token" keyword if present to get just the token value
        token = self.get_token(request)
        # Check for token authentication, secondarily basic auth
        if token and check_auth_token(request, token):
            return True

        if view and (hasattr(view, 'publicly_visible') or
                     super().has_permission(request, view)):
            return True

        if request.path in self.public_views:
            return True

        raise exceptions.NotAuthenticated
