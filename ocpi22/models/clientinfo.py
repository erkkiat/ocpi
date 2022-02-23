from django.db import models
from django.utils import timezone

from ocpi22.choices import ROLE_CHOICES, CONNECTION_STATUS_CHOICES
from ocpi22.util import ModelUtilMixin
from ocpi22.ocpi_util import OcpiModule, Ocpi
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id


class ClientInfo(models.Model, ModelUtilMixin, OcpiModule):
    """
    This module provides parties connected to a hub with the connection status of other parties
    that are connected to a hub that they can communicate with. So, CPOs know which eMSP and other
    parties are online and vice versa.

    Unlike the usual OCPI modules, this module is between eMSP/CPO and Hub instead of between eMSP and CPO.
    """

    ocpi_serializer_class = 'ocpi22.api.ClientInfoSerializer'
    ocpi_module_name = Ocpi.Modules.CLIENTINFO
    ocpi_object_owner = 'HUB'
    send_updates_to = ['EMSP', 'NAP', 'NSP', 'HUB', 'CPO', 'SCSP']

    upper_case_fields = ['country_code', 'party_id']

    # Country code of the country this party is operating in, as used in the credentials exchange.
    country_code = models.CharField(max_length=2, default=get_our_country_code(ocpi_object_owner))

    # CPO or eMSP ID of this party (following the 15118 ISO standard), as used in the credentials exchange.
    party_id = models.CharField(max_length=3, default=get_our_party_id(ocpi_object_owner))

    # The role of the connected party.
    role = models.CharField(max_length=5, choices=ROLE_CHOICES)

    # Status of the connection to the party.
    status = models.CharField(max_length=9, choices=CONNECTION_STATUS_CHOICES)

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.country_code}*{self.party_id} {self.role} is {self.status} ' \
               f'since {self.last_updated.strftime("%Y-%m-%dT%H:%M:%SZ")}'

    def save(self, *args, **kwargs):
        self.change_fields_to_upper_case()
        self.last_updated = timezone.now()
        return super(self.__class__, self).save(*args, **kwargs)
