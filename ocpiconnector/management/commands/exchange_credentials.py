import base64
from json import JSONDecodeError
from logging import getLogger

import cachetools
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated

import ocpi22.ocpi_logging as logging
import os

from django.conf import settings
from django.core import exceptions
from django.core.management.base import BaseCommand

from ocpiconnector.management.commands.serializers import VersionsSerializer

from ocpi22.models.credentials import store_endpoints_for_party, store_tokens_for_party
from ocpi22.ocpi.serializers import CredentialsSerializer
from ocpi22.ocpi.util import ocpi_credentials_get, ocpi_credentials_post
from ocpiconnector.exceptions import OCPIProtocolError, NoCommonVersion
from ocpi22.util import generate_random_token, build_absolute_uri
from ocpiconnector.ocpi_identities import ROLE_OPTIONS

from colorama import Style

from util import reverse

logger = getLogger(__name__)


@cachetools.cached(cache=cachetools.Cache(maxsize=len(ROLE_OPTIONS)))
def get_our_roles(source: dict = None) -> list:
    """
    Get the OCPI roles list of dicts for sending during Credentials exchange

    >>> from util import reverse, HashableDict
    >>> get_our_roles(source=HashableDict(CPO='FI*EON', HUB='FI*HUB', \
    BUSINESS_NAME='Test', BUSINESS_WEBSITE='http://localhost'))
    [{'role': 'CPO', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': 'http://localhost'}, 'party_id': 'EON'}, {'role': 'HUB', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': 'http://localhost'}, 'party_id': 'HUB'}]
    >>> get_our_roles(source=HashableDict(CPO='FI*EON', HUB='FI*HUB', \
    BUSINESS_NAME='Test'))
    [{'role': 'CPO', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': None}, 'party_id': 'EON'}, {'role': 'HUB', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': None}, 'party_id': 'HUB'}]

    @param source: For testing purposes, you can set the source for role settings
    @return: a list of roles formatted for Credentials registration
    """

    source = source or os.environ
    roles = []
    business_name = source.get("BUSINESS_NAME", "N/A")
    website = source.get("BUSINESS_WEBSITE", None)

    for role in ROLE_OPTIONS:
        country_code, party_id = source.get(role, "*").split("*")
        if country_code and party_id:
            roles.append(
                {
                    "role": role,
                    "country_code": country_code,
                    "business_details": {"name": business_name, "website": website},
                    "party_id": party_id,
                }
            )
    return roles
    # Todo: Support multi-country CPOs / eMSPs


def select_version(url, token, credentials_id=None) -> str:
    versions_response = ocpi_credentials_get(url, token, credentials_id=credentials_id)
    if versions_response.status_code == 200:
        data = versions_response.json()
        serializer = VersionsSerializer(data=data)
        if not serializer.is_valid():
            raise ConnectionError(
                f"The Versions endpoint is returning invalid content: {serializer.errors}"
            )
        versions = dict(
            map(lambda x: (x.get("version"), x.get("url")), serializer.data.get("data"))
        )
        version_url = versions.get("2.2.1", versions.get("2.2"))
        if not version_url:
            raise NoCommonVersion("There is no common version available.")
    else:
        raise ConnectionError(
            f"Error connecting: {versions_response.status_code} {versions_response.reason}"
        )

    logging.info(f"CREDENTIALS - Selected version: {version_url}.")
    return version_url


def get_endpoints(url, token, credentials_id=None) -> dict:
    endpoints_response = ocpi_credentials_get(url, token, credentials_id=credentials_id)
    data = endpoints_response.json()
    endpoints = data.get("data", data)
    endpoints_str = ", ".join(set([e["identifier"] for e in endpoints["endpoints"]]))
    logging.info(f"CREDENTIALS - Got endpoints: {endpoints_str}")
    return endpoints


def find_endpoint_url(endpoints, identifier, role) -> str:
    for endpoint in endpoints["endpoints"]:
        ep_identifier = endpoint.get("identifier").lower()
        ep_role = endpoint.get("role").lower()
        if ep_identifier == identifier and ep_role == role:
            credentials_url = endpoint.get("url")
            logging.info(f"Credentials receiver URL: {credentials_url}")
            return credentials_url
    return ""


class Command(BaseCommand):
    help = "Exchange the credentials tokens with a new or existing partner."

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument(
            "token_a", type=str, help="The TOKEN_A provided by the other party"
        )
        parser.add_argument(
            "versions_endpoint_url",
            type=str,
            help="The versions URL provided by the other party",
        )

    def handle(self, *args, **options) -> bool:
        def heading(s):
            logging.info(f"\n\n{Style.BRIGHT}{s}\n{Style.RESET_ALL}")

        token_a = str(options["token_a"])
        token_a_base64 = base64.b64encode(token_a.encode("ascii")).decode("ascii")
        url = options["versions_endpoint_url"]
        assert (
            settings.HOSTNAME not in url
        ), "Cannot register Credentials with ourselves"
        our_token = generate_random_token()
        try:
            heading(
                "1) Getting version info from other party "
                "and selecting a version we both understand"
            )

            version_url = select_version(url, token_a_base64)

            heading("2) Getting endpoints from other party")

            endpoints = get_endpoints(version_url, token_a_base64)
            version = endpoints.get("version")
            credentials = store_tokens_for_party(
                our_token=our_token, their_token=None, token_a=token_a, version=version
            )
            store_endpoints_for_party(credentials, endpoints)

            heading("3) Sending our Credentials Roles to the other party")

            # Get information for all roles present in environment variables
            roles = get_our_roles()
            if not roles:
                raise exceptions.ImproperlyConfigured(
                    f"CREDENTIALS - You need to set the OCPI roles of this Platform in environment variables, "
                    f'e.g. "CPO=NL*EON". The options are: {", ".join(ROLE_OPTIONS)}'
                )

            data_to_send = dict(
                token=our_token,
                url=build_absolute_uri(reverse("base-versions")),
                roles=roles,
            )
            url = find_endpoint_url(
                endpoints, "credentials", "receiver"
            ) or find_endpoint_url(endpoints, "credentials", "sender")
            if not url:
                if credentials:
                    credentials.reset()
                raise OCPIProtocolError(
                    "CREDENTIALS - There is no Credentials Sender or Receiver url provided by the other party"
                )

            credentials_response = ocpi_credentials_post(
                url,
                token_a_base64,
                json=data_to_send,
                timeout=15,
                credentials_id=credentials.id,
            )
            if credentials_response.status_code not in (
                status.HTTP_200_OK,
                status.HTTP_201_CREATED,
            ):
                msg = f"CREDENTIALS - Endpoints returned HTTP {credentials_response.status_code} from Credentials Receiver"
                if credentials:
                    credentials.reset()
                raise OCPIProtocolError(msg)
            data = credentials_response.json()
            data = data.get("data", data)
            serializer = CredentialsSerializer(data=data, instance=credentials)
            if serializer.is_valid():
                serializer.save()
            else:
                msg = f"CREDENTIALS - Response from Credentials Receiver is invalid: {serializer.errors}"
                if credentials:
                    credentials.reset()
                raise OCPIProtocolError(msg)
            credentials.disable_token_a_if_applicable()
            return True

        except (JSONDecodeError, NotAuthenticated) as e:
            logging.error(f"CREDENTIALS - Credentials exchange protocol error: {e}")
            print(f"*** There has been a protocol error: {str(e)}")
            raise
        except (OSError, IOError) as e:
            logging.error(f"CREDENTIALS - Cannot reach the specified endpoint: {e}")
            print(f"*** Cannot reach the URL you specified: {str(e)}")
            raise
