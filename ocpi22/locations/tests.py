import base64
import doctest
import json
import os
from typing import Optional, Mapping, Any
from urllib.parse import urljoin

import requests
from rest_framework.exceptions import NotAuthenticated

import ocpi22.logging as logging
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass

from datetime import timedelta, datetime
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock, AsyncMock

import pytz
import redis.exceptions
import time_machine
from django.conf import settings
from django.http import HttpResponse

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase, Client

import json
from datetime import datetime
from unittest import TestCase

import pytz
from icecream import ic

from ocpi22.locations.serializers import LocationSerializer221
from ocpiconnector.testutil import OCPIAPIRequestFactory

faketime = datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc)
client = Client()
dirname = os.path.dirname(os.path.abspath(__file__))
api_factory = OCPIAPIRequestFactory()


def load_json(filename, serializer):
    with open(filename) as fp:
        data = json.load(fp)
        return serializer(data).data


class TestLocations(TestCase):
    def test_serialization(self):
        location = load_json('ocpi22/data/examples/location_example_parking_garage_opening_hours.json', LocationSerializer221)
        ic(location)
