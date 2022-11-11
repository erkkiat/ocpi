import ocpi22.logging as logging
from argparse import ArgumentParser

import requests
from django.core.management.base import BaseCommand
from icecream import ic
from requests import Response

from ocpi22.locations.serializers import LocationSerializer
from ocpi22.models.credentials import Endpoint


class Command(BaseCommand):
    help = 'Pull locations from all parties with "Locations sender".'

    class ProtocolError(Exception):
        pass

    def ocpi_get(self, url, token_base64):
        self.stdout.write(f'Getting {url}')
        response = requests.get(url, headers=dict(Authorization=f'Token {token_base64}'), timeout=20)
        if response.status_code != 200:
            self.stdout.write(f'*** Got response: {response.status_code} - {response.reason}')
            self.stdout.write(response.text)
            raise self.ProtocolError(f'Got response for {url}: {response.status_code} - {response.reason}')
        return response

    def add_arguments(self, parser: ArgumentParser):
        # Positional arguments
        parser.add_argument('--clear',
                            help='Clear the Locations before pull (NOT for use in production!)')

    def handle(self, *args, **options):
        ic(args, options)
        # clear = options['clear']
        endpoints = Endpoint.objects.filter(identifier='locations', role='SENDER')
        for endpoint in endpoints:
            url = endpoint.url
            token = endpoint.get_token_base64()
            response: Response = self.ocpi_get(url, token)
            data = response.json()['data']
            # ic(response.json())
            for location in data:
                ic(location)
                serializer = LocationSerializer(data=location)
                if serializer.is_valid():
                    ic(serializer.data)
                    # serializer.save()
                else:
                    logging.warning(f'Parsing error from {endpoint.credentials.party()} {url}'
                                    f'{serializer.errors}')
