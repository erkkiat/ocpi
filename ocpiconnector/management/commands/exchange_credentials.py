import requests
from django.core.management.base import BaseCommand
from icecream import ic



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

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('token_a', type=str)
        parser.add_argument('credentials_url', type=str)

        # parser.add_argument(
        #     '--delete',
        #     action='store_true',
        #     help='Delete poll instead of closing it',
        # )

    def handle(self, *args, **options):
        token_a = options['token_a']
        url = options['credentials_url']
        # Todo: token_b = generate token
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
                ic(endpoints_response.json())
            else:
                print(f'*** Error connecting: {versions_response.status_code} {versions_response.reason}')
        except requests.exceptions.ConnectionError as e:
            print(f'*** Cannot reach the URL you specified: {str(e)}')
