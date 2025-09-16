import base64
from logging import getLogger

import binascii
import os
from enum import Enum
from functools import cache
from typing import Optional

from cachetools import cached, TTLCache
from cachetools.func import ttl_cache
from cachetools.keys import hashkey
from django.conf import settings
from django.contrib.auth import authenticate
from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.security import HttpBasicAuth, HttpBearer
from rest_framework import exceptions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import DjangoModelPermissions

from ocpi22.choices import OcpiRolesEnum
from ocpiconnector.db_services import ensure_db_connection
from ocpi22.ocpi.util_party import get_sender_party
from ocpiconnector.ocpi_identities import create_credentialsrole, ocpi_identities
from ocpiconnector.party import Party
from util import reverse

from ocpi22.models.credentials import Credentials, CredentialsRole

logger = getLogger(__name__)


class OcpiAuthTypes(Enum):
    NONE = 0
    TOKEN_A = 1
    FINAL = 2

    def __eq__(self, other):
        return self.value == other or self is other


@ttl_cache(maxsize=settings.MAX_NUMBER_OF_PARTNERS, ttl=2 * 60 * 60)  # 2 hours
def find_credentials(token_ascii: str) -> Optional[Credentials]:
    try:
        return Credentials.objects.filter(ours=token_ascii, valid=True).first()
    except (binascii.Error, UnicodeDecodeError):
        pass
    return None


def check_auth_token(request, token: str) -> bool:
    @cache
    def allowed_for_token_a():
        # ('/ocpi/versions/', '/ocpi/2.2/credentials/', '/ocpi/2.2.1/credentials/', '/ocpi/2.2/', '/ocpi/2.2.1/', '/')
        result = {
            reverse("base-versions"),  # The "Versions" endpoint
            # reverse('credentials-list', args=['2.2']),  # Getting the Credentials
            # reverse('credentials-list', args=['2.2.1']),  # Getting the Credentials
            "/",  # The front page, which serves as HTML page and versions endpoint
        }
        result.update(settings.VERSION_URLS)
        result.update(
            reverse("credentials-list", args=[version]) for version in settings.VERSIONS
        )
        return result

    # Only certain endpoints can be accessed using TOKEN_A during the credentials exchange
    try:
        request.ocpi_auth = OcpiAuthTypes.NONE
        request.ocpi_party = None
        if not token:
            return False
        token_ascii = base64.b64decode(token).decode("ascii")
        credentials = find_credentials(
            token_ascii
        )  # This is the typical case, that's why it's a cached function
        if credentials:
            request.credentials = credentials
        else:
            request.registering_credentials = request.path in allowed_for_token_a()

            # First check for TOKEN_A, are we still getting to know each other?
            credentials_matches = Credentials.objects.filter(
                token_a=token_ascii, valid=True
            )
            if credentials_matches.exists():
                if not getattr(request, "registering_credentials", None):
                    raise exceptions.NotAuthenticated(  # HTTP 401
                        f'TOKEN_A can only be used for the Credentials and Versions modules, not for path "{request.path}".'
                    )

                # Don't accept TOKEN_A anymore, if tokens have been exchanged
                # NOTE: At a given time, one party may possess all three tokens while the other has only two

                credentials = credentials_matches.first()
                request.credentials = credentials
            else:
                raise NotAuthenticated(  # HTTP 401
                    f'The token "{token}" (ascii {token_ascii}) doesn\'t match any of our current credentials'
                    if settings.DEBUG
                    else ""
                )

        sender_party = get_sender_party(request.headers)
        if not sender_party and credentials.roles.count() == 1:
            sender_party = credentials.roles.first().get_party()

        if credentials.is_hub:
            # Implicit trust for hubs, since there is no hub authentication in OCPI 2.x
            request.ocpi_party = get_credentialsrole(
                credentials=None, party=sender_party, create=True
            )
        else:
            # Make sure we know if the credentials is being registered or not
            request.registering_credentials = (
                getattr(request, "registering_credentials", None)
                or request.path in allowed_for_token_a()
            )
            request.ocpi_party = get_credentialsrole(
                request.credentials, party=sender_party
            )
            if not getattr(request, "ocpi_party", None) and not getattr(
                request, "registering_credentials", None
            ):
                request.credentials = None
                raise NotAuthenticated(
                    f"Sender party {sender_party} is not allowed for these credentials"
                )

        return True

    except (binascii.Error, UnicodeDecodeError) as e:
        raise NotAuthenticated(f"Authentication token: {e}")


@cached(
    cache=TTLCache(maxsize=settings.MAX_NUMBER_OF_PARTNERS, ttl=24 * 60 * 60),
    key=lambda credentials=None, party=None, create=False, role=None: hashkey(
        credentials.pk if credentials else None, party, role
    ),
)  # Ignore the create flag
@ensure_db_connection
def get_credentialsrole(
    credentials: Optional[Credentials] = None,
    party: Party = None,
    create=False,
    role: OcpiRolesEnum = None,
) -> Optional[CredentialsRole]:
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
        business_name = "N/A"
        website = ""
        # Is this (one of) our identity?
        if str(party) in ocpi_identities:
            business_name = os.environ.get("BUSINESS_NAME", "N/A")
            website = os.environ.get("BUSINESS_WEBSITE", None)
        credentialsrole = create_credentialsrole(
            Party(
                country_code=party.country_code.upper(), party_id=party.party_id.upper()
            ),
            business_name=business_name,
            website=website,
            role=role or OcpiRolesEnum.OTHER,
            credentials=credentials,
        )
        return credentialsrole

    try:
        query = (
            credentials.roles.all() if credentials else CredentialsRole.objects.all()
        )
        result = query.filter(
            country_code__iexact=party.country_code, party_id__iexact=party.party_id
        ).first()
        return result if result is not None else (create_it() if create else None)
    except CredentialsRole.DoesNotExist:
        if create:
            return create_it()
        return None


class OCPIPermission(DjangoModelPermissions):
    """
    Check for valid OCPI authentication header and secondarily basic auth with local user IDs
    """

    perms_map = {
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": [],
        "HEAD": [],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }

    @staticmethod
    def get_token(request) -> str:
        authorization = request.META.get(
            "HTTP_AUTHORIZATION",
            request.META.get("Authorization", request.GET.get("auth-test", "")),
        )
        if authorization.startswith("Token "):
            return authorization[6:]
        return ""

    def has_permission(self, request, view=None):
        # Get the OCPI Authorization header or if none, the auth-test query param
        # Remove the "Token" keyword if present to get just the token value
        token = self.get_token(request)

        # Check for token authentication
        if check_auth_token(request, token) and (
            getattr(request, "registering_credentials", None)
            or getattr(request, "ocpi_party", None)
        ):
            return True

        # Check for basic authentication
        if view and (
            hasattr(view, "publicly_visible") or super().has_permission(request, view)
        ):
            return True

        logger.warning(f"No valid authentication for {request.path} (token: {token})")
        raise exceptions.NotAuthenticated


class NinjaBasicAuth(HttpBasicAuth):
    def authenticate(self, request, username, password):
        try:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if user.is_authenticated:
                    request.user = user
                    return user
            return None
        except exceptions.AuthenticationFailed:
            return None


class HubjectCertAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str = None):
        if settings.ENV == "development":
            return {"ip": "", "cert": "development-mode"}

        ip = request.META.get("REMOTE_ADDR")
        if ip not in settings.HUBJECT_HOSTS:
            raise HttpError(403, "Forbidden: IP not allowed")

        cert_pem = request.META.get("HTTP_X_SSL_CLIENT_CERT")
        verify_status = request.META.get("HTTP_X_SSL_CLIENT_VERIFY")

        if verify_status != "SUCCESS" or not cert_pem:
            raise HttpError(403, "Forbidden: Invalid client certificate")

        return {"ip": ip, "cert": cert_pem}
