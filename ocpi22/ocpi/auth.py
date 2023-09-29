import base64
import binascii
from functools import cache
from typing import Optional

from django.conf import settings
from django.utils.functional import cached_property
from rest_framework import exceptions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import DjangoModelPermissions

from ocpi22.choices import OcpiRolesEnum
from ocpi22.ocpi.util_party import get_sender_party
from ocpiconnector.ocpi_identities import Party, create_credentialsrole
from util import reverse

from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpiconnector.settings import PUBLIC_VIEWS


class OcpiAuthTypes:
    NONE = 0
    TOKEN_A = 1
    FINAL = 2


def check_auth_token(request, token: str) -> bool:
    @cache
    def allowed_for_token_a():
        return (
            reverse('base-versions'),  # The "Versions" endpoint
            reverse('credentials-list', args=['2.2']),  # Getting the Credentials
            reverse('credentials-list', args=['2.2.1']),  # Getting the Credentials
            settings.OCPI_22_URL,  # The "Endpoints" endpoint
            settings.OCPI_221_URL,  # The "Endpoints" endpoint
            '/',  # The front page, which serves as HTML page and versions endpoint
        )

    # Only certain endpoints can be accessed using TOKEN_A during the credentials exchange
    try:
        if not token:
            return False
        token_ascii = base64.b64decode(token).decode('ascii')
        request.ocpi_auth = OcpiAuthTypes.NONE
        request.ocpi_party = None

        # First check for TOKEN_A, are we still getting to know each other?
        credentials_matches = Credentials.objects.filter(token_a=token_ascii, valid=True)
        if credentials_matches.count():
            if request.path not in allowed_for_token_a():
                raise exceptions.NotAuthenticated(  # HTTP 401
                    f'TOKEN_A can only be used for the Credentials and Versions modules, not for path "{request.path}".'
                )

            # Don't accept TOKEN_A anymore, if tokens have been exchanged
            # NOTE: At a given time, one party may possess all three tokens while the other has only two

            credentials = credentials_matches.first()
            request.ocpi_auth = OcpiAuthTypes.TOKEN_A
            request.credentials = credentials
        else:
            # Or are we already best friends?
            credentials_matches = Credentials.objects.filter(ours=token_ascii, valid=True)
            if credentials_matches.count():
                credentials = credentials_matches.first()
                request.ocpi_auth = OcpiAuthTypes.FINAL
                request.credentials = credentials
            else:
                raise exceptions.NotAuthenticated(  # HTTP 401
                    f'The token "{token}" (ascii {token_ascii}) doesn\'t match any of our current credentials'
                )

            sender_party = get_sender_party(request.headers)

            if credentials.is_hub:
                # Implicit trust for hubs, since there is no hub authentication in OCPI 2.x
                request.ocpi_party = get_credentialsrole(
                    credentials=None, party=sender_party, create=True
                )
            else:
                request.ocpi_party = get_credentialsrole(request.credentials, party=sender_party)
                if not request.ocpi_party:
                    request.credentials = None
                    raise NotAuthenticated(f'Sender party {sender_party} is not allowed for these credentials')

        return True

    except (binascii.Error, UnicodeDecodeError) as e:
        raise NotAuthenticated(f'Authentication token: {e}')


def get_credentialsrole(credentials: Optional[Credentials], party: Party, create=False, role=None) -> Optional[CredentialsRole]:
    """
    Find the CredentialsRole for the given party and credentials
    If we received a message through a hub, we may not know the sender yet, so we need to create a CredentialsRole to
    be able to process the message.

    @param credentials: The sender's credentials, so we know which CredentialsRoles are allowed for them
    @param party: Sender's party ID for choosing the CredentialsRole
    @param role: The role, if a CredentialsRole is created
    @param create: Should we create the CredentialsRole if it doesn't exist yet?
    @return: The selected or created CredentialsRole
    """

    def create_it():
        credentialsrole = create_credentialsrole(
            Party(country_code=party.country_code.upper(), party_id=party.party_id.upper()),
            business_name='N/A', website='', role=role or OcpiRolesEnum.OTHER, credentials=credentials
        )
        return credentialsrole

    try:
        query = credentials.roles.all() if credentials else CredentialsRole.objects.all()
        result = query.filter(country_code__iexact=party.country_code,
                            party_id__iexact=party.party_id).first()
        return result or (create and create_it())
    except CredentialsRole.DoesNotExist:
        if create:
            return create_it()
        return None


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
        return {reverse(i) for i in PUBLIC_VIEWS}

    def has_permission(self, request, view=None):
        # Get the OCPI Authorization header or if none, the auth-test query param
        # Remove the "Token" keyword if present to get just the token value
        token = self.get_token(request)

        # Check for token authentication, secondarily basic auth
        if check_auth_token(request, token) and (request.ocpi_auth == OcpiAuthTypes.TOKEN_A or request.ocpi_party):
            return True

        if view and (hasattr(view, 'publicly_visible') or super().has_permission(request, view)):
            return True

        if request.path in self.public_views:
            return True

        raise exceptions.NotAuthenticated
