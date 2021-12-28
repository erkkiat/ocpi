import base64
import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from rest_framework.reverse import reverse

from ocpi22.models import Endpoint, Credentials
from ocpi22.util import generate_random_token

from colorama import Back, Style


class Command(BaseCommand):
    help = 'Exchange the credentials tokens with a new or existing partner.'

    class NoCommonVersion(Exception):
        pass

    class ProtocolError(Exception):
        pass

    def ocpi_get(self, url, token_base64):
        self.stdout.write(f'Getting {url}')
        response = requests.get(url, headers=dict(Authorization=f'Token {token_base64}'))
        if response.status_code != 200:
            self.stdout.write(f'{Back.RED}*** Got response: {response.status_code} - {response.reason}')
            self.stdout.write(response.text)
            raise self.ProtocolError(f'Got response for {url}: {response.status_code} - {response.reason}')
        return response

    def ocpi_post(self, url, token_base64, *args, **kwargs):
        self.stdout.write(f'Posting to {url}')
        response = requests.post(url=url, headers=dict(Authorization=f'Token {token_base64}'), *args, **kwargs)
        if response.status_code != 200:
            self.stdout.write(f'*** Got response: {response.status_code} - {response.reason}')
            self.stdout.write(response.text)
            raise self.ProtocolError(f'Got response for {url}: {response.status_code} - {response.reason}')
        return response

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('token_a', type=str, help='The TOKEN_A provided by the other party')
        parser.add_argument('credentials_url', type=str, help='The credentials URL provided by the other party')

        # parser.add_argument(
        #     '--delete',
        #     action='store_true',
        #     help='Delete poll instead of closing it',
        # )

    def __select_version(self, url, token):
        selected_version = None
        versions_response = self.ocpi_get(url, token)
        if versions_response.status_code == 200:
            # ic(versions_response.json())
            for version_option in versions_response.json():
                if "version" not in version_option or "url" not in version_option:
                    raise SyntaxError('Version information not found in received data. '
                                      'Make sure you have the OCPI versions URL.')
                # ic(version_option)
                # Todo: Support earlier versions also
                if version_option['version'] == '2.2':
                    selected_version = version_option
                    break
            if not selected_version:
                raise self.NoCommonVersion('There is no common version available.')
        else:
            print(f'*** Error connecting: {versions_response.status_code} {versions_response.reason}')

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
                # self.stdout.write(f'Credentials receiver URL: {credentials_url}')
                return credentials_url
        raise self.ProtocolError('There is no credentials_url provided by the other party')

    def handle(self, *args, **options):
        def heading(s):
            self.stdout.write(f"\n\n{Style.BRIGHT}{s}\n\n{Style.RESET_ALL}")

        token_base64 = options['token_a']
        url = options['credentials_url']
        token_b = generate_random_token().upper()
        try:
            heading('1) Getting version info from other party '
                              'and selecting a version we both understand')

            selected_version = self.__select_version(url, token_base64)
            self.stdout.write(f'Selected version: {selected_version}.')

            heading('2) Getting endpoints from other party')

            endpoints = self.__get_endpoints(selected_version['url'], token_base64)
            endpoints_str = ", ".join(set([e['identifier'] for e in endpoints['endpoints']]))
            self.stdout.write(f'Got endpoints: {endpoints_str}')

            token = base64.b64decode(token_base64).decode('ascii')

            credentials = Credentials.find(token, create=True)
            credentials.ours = token_b
            credentials.version = endpoints['version'].replace('.', '')  # "2.2" => "22"
            credentials.save()

            # Replace any existing endpoints for this specific party
            credentials.endpoints.all().delete()

            for ep in endpoints['endpoints']:
                endpoint = Endpoint(**ep)
                endpoint.credentials = credentials
                endpoint.save()

            heading('3) Sending our Credentials Roles to the other party')

            data_to_send = dict(
                token=token_b,
                url=f'http://{settings.HOSTNAME}{reverse("base-versions")}',
                roles=[dict(
                    role='CPO',
                    business_details=dict(name=os.environ.get('BUSINESS_NAME', 'N/A')),
                    party_id=os.environ.get('PARTY_ID', 'XXX'),
                    country_code=os.environ.get('COUNTRY_CODE', 'XX')
                ),
                    dict(
                        role='EMSP',
                        business_details=dict(name=os.environ.get('BUSINESS_NAME', 'N/A')),
                        party_id=os.environ.get('PARTY_ID', 'XXX'),
                        country_code=os.environ.get('COUNTRY_CODE', 'XX')
                    )
                ],
            )
            _credentials_response = self.ocpi_post(
                self.find_endpoint_url(endpoints, 'credentials', 'receiver'),
                token_base64,
                json=data_to_send
            )

        except requests.exceptions.ConnectionError as e:
            print(f'{Back.RED}*** Cannot reach the URL you specified: {str(e)}')
        except self.ProtocolError as e:
            print(f'{Back.RED}*** There has been a protocol error: {str(e)}')
