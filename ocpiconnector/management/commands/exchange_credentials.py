import base64
from json import JSONDecodeError

import cachetools
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated

import ocpi22.logging as logging
import os

import requests
from django.conf import settings
from django.core import exceptions
from django.core.management.base import BaseCommand

from certification.decorators import certification_step
from ocpi22.choices import OcpiModuleEnum
from ocpi22.tasks import send_ocpi_request
from ocpiconnector.exception_handler import ocpi_exception_handler
from util import reverse, HashableDict

from ocpi22.models.credentials import store_endpoints_for_party, store_tokens_for_party
from ocpi22.ocpi.serializers import CredentialsSerializer
from ocpi22.ocpi.util import ocpi_credentials_get, ocpi_credentials_post
from ocpiconnector.exceptions import OCPIProtocolError, NoCommonVersion
from ocpi22.util import generate_random_token
from ocpiconnector.ocpi_identities import ROLE_OPTIONS

from colorama import Style

cache = cachetools.Cache(maxsize=len(ROLE_OPTIONS))


@cachetools.cached(cache)
def get_our_roles(source: dict = None) -> list:
    """
    Get the OCPI roles list of dicts for sending during Credentials exchange

    >>> get_our_roles(source=HashableDict(CPO='FI*EON', HUB='FI*HUB', \
    BUSINESS_NAME='Test', BUSINESS_WEBSITE='http://example.com'))
    [{'role': 'CPO', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': 'http://example.com'}, 'party_id': 'EON'}, {'role': 'HUB', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': 'http://example.com'}, 'party_id': 'HUB'}]

    @param source: For testing purposes, you can set the source for role settings
    @return: a list of roles formatted for Credentials registration
    """

    source = source or os.environ
    roles = []
    business_name = source.get('BUSINESS_NAME', 'N/A')
    website = source.get('BUSINESS_WEBSITE', '')

    for role in ROLE_OPTIONS:
        country_code, party_id = source.get(role, "*").split('*')
        if country_code and party_id:
            roles.append(
                dict(
                    role=role,
                    country_code=country_code,
                    business_details=dict(name=business_name, website=website),
                    party_id=party_id,
                )
            )
    return roles
    # Todo: Support multi-country CPOs / eMSPs


class NoCommonVersion(SyntaxError):
    pass


def select_version(url, token) -> str:
    versions_response = ocpi_credentials_get(url, token)
    if versions_response.status_code == 200:
        data = versions_response.json()
        if not isinstance(data, dict):
            raise OCPIProtocolError(f'Expecting a data element in response from version endpoint, '
                                    f'got "{data}"')
        data = data.get('data', data)
        versions = dict(map(lambda x: (x.get('version'), x.get('url')), data))
        version_url = versions.get('2.2.1', versions.get('2.2'))
        if not version_url:
            raise NoCommonVersion('There is no common version available.')
    else:
        raise ConnectionError(f'Error connecting: {versions_response.status_code} {versions_response.reason}')

    logging.info(f'CREDENTIALS - Selected version: {version_url}.')
    return version_url


def get_endpoints(url, token):
    endpoints_response = ocpi_credentials_get(url, token)
    data = endpoints_response.json()
    endpoints = data.get('data', data)
    endpoints_str = ", ".join(set([e['identifier'] for e in endpoints['endpoints']]))
    logging.info(f'CREDENTIALS - Got endpoints: {endpoints_str}')
    return endpoints


def find_endpoint_url(endpoints, identifier, role) -> str:
    for endpoint in endpoints['endpoints']:
        ep_identifier = endpoint.get('identifier').lower()
        ep_role = endpoint.get('role').lower()
        if ep_identifier == identifier and ep_role == role:
            credentials_url = endpoint.get('url')
            logging.info(f'Credentials receiver URL: {credentials_url}')
            return credentials_url
    return ''


class Command(BaseCommand):
    help = 'Exchange the credentials tokens with a new or existing partner.'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('token_a', type=str, help='The TOKEN_A provided by the other party')
        parser.add_argument('versions_endpoint_url', type=str, help='The versions URL provided by the other party')

    @ocpi_exception_handler
    @certification_step(OcpiModuleEnum.CREDENTIALS, 'Establish new Credentials as a sender')
    def handle(self, *args, **options) -> bool:
        def heading(s):
            logging.info(f"\n\n{Style.BRIGHT}{s}\n{Style.RESET_ALL}")

        token_a = str(options['token_a'])
        token_a_base64 = base64.b64encode(token_a.encode('ascii')).decode('ascii')
        url = options['versions_endpoint_url']
        assert settings.HOSTNAME not in url, 'Cannot register Credentials with ourselves'
        our_token = generate_random_token()
        try:
            heading('1) Getting version info from other party '
                    'and selecting a version we both understand')

            version_url = select_version(url, token_a_base64)

            heading('2) Getting endpoints from other party')

            endpoints = get_endpoints(version_url, token_a_base64)
            version = endpoints.get('version')
            credentials = store_tokens_for_party(our_token=our_token, their_token=None, token_a=token_a,
                                                 version=version)
            store_endpoints_for_party(credentials, endpoints)

            heading('3) Sending our Credentials Roles to the other party')

            # Get information for all roles present in environment variables
            roles = get_our_roles()
            if not roles:
                raise exceptions.ImproperlyConfigured(
                    f'CREDENTIALS - You need to set the OCPI roles of this Platform in environment variables, '
                    f'e.g. "CPO=NL*EON". The options are: {", ".join(ROLE_OPTIONS)}')

            data_to_send = dict(
                token=our_token,
                url=f'http://{settings.HOSTNAME}{reverse("base-versions")}',
                roles=roles,
            )
            url = find_endpoint_url(endpoints, 'credentials', 'receiver') or \
                find_endpoint_url(endpoints, 'credentials', 'sender')
            if not url:
                if credentials:
                    credentials.reset()
                raise OCPIProtocolError(
                    f'CREDENTIALS - There is no Credentials Sender or Receiver url provided by the other party')

            credentials_response = ocpi_credentials_post(url, token_a_base64, json=data_to_send, timeout=15)
            if credentials_response.status_code != status.HTTP_200_OK:
                msg = f'CREDENTIALS - Endpoints returned HTTP {credentials_response.status_code} from Credentials Receiver'
                if credentials:
                    credentials.reset()
                raise OCPIProtocolError(msg)
            data = credentials_response.json()
            data = data.get('data', data)
            serializer = CredentialsSerializer(data=data, instance=credentials)
            if serializer.is_valid():
                serializer.save()
            else:
                msg = f'CREDENTIALS - Response from Credentials Receiver is invalid: {serializer.errors}'
                if credentials:
                    credentials.reset()
                raise OCPIProtocolError(msg)
            return True

        except OSError as e:
            logging.error(f'CREDENTIALS - Cannot reach the specified endpoint: {e}')
            print(f'*** Cannot reach the URL you specified: {str(e)}')
            raise
        except (JSONDecodeError, NotAuthenticated) as e:
            logging.error(f'CREDENTIALS - Credentials exchange protocol error: {e}')
            print(f'*** There has been a protocol error: {str(e)}')
            raise
