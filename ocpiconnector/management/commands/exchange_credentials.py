import base64
import logging
import os

import requests
from django.conf import settings
from django.core import exceptions
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.reverse import reverse

from ocpi22.models.credentials import Credentials, Endpoint, find_endpoints_by_roles
from ocpi22.util import generate_random_token
from ocpiconnector.ocpi_identities import ROLE_OPTIONS

from colorama import Back, Style


def get_our_roles(source: dict = os.environ) -> list:
    """
    Get the OCPI roles list of dicts for sending during Credentials exchange

    >>> get_our_roles(source=dict(CPO='FI*EON', HUB='FI*HUB', \
    BUSINESS_NAME='Test', BUSINESS_WEBSITE='http://example.com'))
    [{'role': 'CPO', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': 'http://example.com'}, 'party_id': 'EON'}, {'role': 'HUB', 'country_code': 'FI', 'business_details': {'name': 'Test', 'website': 'http://example.com'}, 'party_id': 'HUB'}]

    >>> get_our_roles(source=dict())
    []

    @param source: For testing purposes, you can set the source for role settings
    @return:
    """

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


class OCPIProtocolError(SyntaxError):
    errno = None

    def __init__(self, msg, errno=None):
        super().__init__(msg)
        self.errno = errno


class Command(BaseCommand):
    help = 'Exchange the credentials tokens with a new or existing partner.'

    def ocpi_get(self, url, token_base64):
        logging.info(f'Getting {url}')
        response = requests.get(url, headers=dict(Authorization=f'Token {token_base64}'))
        if response.status_code != 200:
            logging.info(f'{Back.RED}*** Got response: {response.status_code} - {response.reason}')
            logging.info(response.text)
            raise OCPIProtocolError(f'Got response for {url}: {response.status_code} - {response.reason}',
                                    errno=response.status_code)
        return response

    def ocpi_post(self, url, token_base64, *args, **kwargs):
        logging.info(f'Posting to {url}')
        response = requests.post(url=url, headers=dict(Authorization=f'Token {token_base64}'), *args, **kwargs)
        if response.status_code != 200:
            logging.info(f'*** Got response: {response.status_code} - {response.reason}')
            logging.info(response.text)
            raise OCPIProtocolError(f'Got response for {url}: {response.status_code} - {response.reason}',
                                    errno=response.status_code)
        return response

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('token_a', type=str, help='The TOKEN_A provided by the other party')
        parser.add_argument('versions_endpoint_url', type=str, help='The versions URL provided by the other party')

    def __select_version(self, url, token):
        selected_version = None
        versions_response = self.ocpi_get(url, token)
        if versions_response.status_code == 200:
            # ic(versions_response.json())
            for version_option in versions_response.json():
                if "version" not in version_option or "url" not in version_option:
                    raise OCPIProtocolError('Version information not found in received data. '
                                            'Make sure you have the OCPI versions URL.')
                # ic(version_option)
                # Todo: Support earlier versions also
                if version_option['version'] == '2.2':
                    selected_version = version_option
                    break
            if not selected_version:
                raise self.NoCommonVersion('There is no common version available.')
        else:
            raise ConnectionError(f'Error connecting: {versions_response.status_code} {versions_response.reason}')

        return selected_version

    def __get_endpoints(self, url, token):
        endpoints_response = self.ocpi_get(url, token)
        return endpoints_response.json()

    def find_endpoint_url(self, endpoints, identifier, role):
        for endpoint in endpoints['endpoints']:
            ep_identifier = endpoint.get('identifier').lower()
            ep_role = endpoint.get('role').lower()
            if ep_identifier == identifier and ep_role == role:
                credentials_url = endpoint.get('url')
                # logging.info(f'Credentials receiver URL: {credentials_url}')
                return credentials_url
        raise OCPIProtocolError('There is no credentials_url provided by the other party')

    def handle(self, *args, **options):
        def heading(s):
            logging.info(f"\n\n{Style.BRIGHT}{s}\n{Style.RESET_ALL}")

        token_base64 = base64.b64encode(str(options['token_a']).encode('ascii')).decode('ascii')
        url = options['versions_endpoint_url']
        token_b = generate_random_token().upper()
        try:
            heading('1) Getting version info from other party '
                    'and selecting a version we both understand')

            selected_version = self.__select_version(url, token_base64)
            logging.info(f'Selected version: {selected_version}.')

            heading('2) Getting endpoints from other party')

            endpoints = self.__get_endpoints(selected_version['url'], token_base64)
            endpoints_str = ", ".join(set([e['identifier'] for e in endpoints['endpoints']]))
            logging.info(f'Got endpoints: {endpoints_str}')

            token = base64.b64decode(token_base64).decode('ascii')

            credentials: Credentials = Credentials.find(token, create=True)
            credentials.ours = token_b
            credentials.version = endpoints['version'].replace('.', '')  # "2.2" => "22"
            credentials.last_connection = timezone.now()
            credentials.save()

            # Replace any existing endpoints for this specific party
            # noinspection PyUnresolvedReferences
            credentials.endpoints.all().delete()

            for ep in endpoints['endpoints']:
                endpoint = Endpoint(**ep)
                endpoint.credentials = credentials
                endpoint.save()

            heading('3) Sending our Credentials Roles to the other party')

            # Get information for all roles present in environment variables
            roles = get_our_roles()
            if not roles:
                raise exceptions.ImproperlyConfigured(
                    f'You need to set the OCPI roles of this Platform in environment variables, '
                    f'e.g. "CPO=NL*EON". The options are: {", ".join(ROLE_OPTIONS)}')

            data_to_send = dict(
                token=token_b,
                url=f'http://{settings.HOSTNAME}{reverse("base-versions")}',
                roles=roles,
            )
            _credentials_response = self.ocpi_post(
                self.find_endpoint_url(endpoints, 'credentials', 'receiver'),
                token_base64,
                json=data_to_send
            )
            # ic(_credentials_response)
            if credentials.ours and credentials.theirs:
                heading(Style.BRIGHT + 'Credentials exchange has been finished successfully.' + Style.RESET_ALL)
                find_endpoints_by_roles.cache_clear()
            else:
                heading('Credentials exchange first part was successful, now initiate from the other end.')

            return True

        except requests.exceptions.ConnectionError as e:
            print(f'{Back.RED}*** Cannot reach the URL you specified: {str(e)}')
            raise
        except OCPIProtocolError as e:
            print(f'{Back.RED}*** There has been a protocol error: {str(e)}')
            raise
