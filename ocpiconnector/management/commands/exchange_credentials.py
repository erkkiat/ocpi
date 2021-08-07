import os
import secrets

import requests
from django.core.management.base import BaseCommand
from icecream import ic
from rest_framework.reverse import reverse


class Command(BaseCommand):
    help = 'Exchange the credentials tokens with a new or existing partner.'

    class NoCommonVersion(Exception):
        pass

    def ocpi_get(self, url, token):
        self.stdout.write(f'Getting {url}')
        response = requests.get(url, headers=dict(Authorization=f'Token {token}'))
        if response.status_code != 200:
            self.stdout.write(f'*** Got response: {response.status_code} - {response.reason}')
            self.stdout.write(response.text)
        return response

    def ocpi_post(self, url, token, *args, **kwargs):
        self.stdout.write(f'Posting to {url}')
        response = requests.post(url, headers=dict(Authorization=f'Token {token}'), *args, **kwargs)
        if response.status_code != 200:
            self.stdout.write(f'*** Got response: {response.status_code} - {response.reason}')
            self.stdout.write(response.text)
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

    def handle(self, *args, **options):
        token_a = options['token_a']
        url = options['credentials_url']
        token_b = secrets.token_hex(64)
        try:
            selected_version = None
            versions_response = self.ocpi_get(url, token_a)
            if versions_response.status_code == 200:
                for version_option in versions_response.json():
                    # Todo: Support earlier versions also
                    if version_option['version'] == '2.2':
                        selected_version = version_option
                        break
                if not selected_version:
                    raise self.NoCommonVersion('There is no common version available.')
                self.stdout.write(f'Selected version: {selected_version}.')

                endpoints_response = self.ocpi_get(selected_version['url'], token_a)
                if endpoints_response.status_code == 200:
                    endpoints_json = endpoints_response.json()
                    for endpoint in endpoints_json['endpoints']:
                        identifier = endpoint.get('identifier').lower()
                        role = endpoint.get('role').lower()
                        if identifier == 'credentials' and role == 'receiver':
                            credentials_url = endpoint.get('url')
                            self.stdout.write(f'Credentials receiver URL: {credentials_url}')
                            roles = [
                                dict(
                                    role='CPO',
                                    business_details=dict(name=os.environ.get('BUSINESS_NAME', '')),
                                    party_id=os.environ.get('PARTY_ID', 'XXX'),
                                    country_code=os.environ.get('COUNTRY_CODE', 'XX')
                                ),
                            ]
                            data_to_send = dict(
                                token=token_b,
                                url=f'http://localhost:8000{reverse("base-versions")}',
                                roles=roles
                            )
                            ic(data_to_send)
                            credentials_response = self.ocpi_post(
                                credentials_url,
                                token_a,
                                data=data_to_send
                            )
            else:
                print(f'*** Error connecting: {versions_response.status_code} {versions_response.reason}')
        except requests.exceptions.ConnectionError as e:
            print(f'*** Cannot reach the URL you specified: {str(e)}')
