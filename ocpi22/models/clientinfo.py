from django.db import models
from django.utils import timezone

from ocpi22.choices import ROLE_CHOICES, CONNECTION_STATUS_CHOICES
from ocpi22.models.credentials import CredentialsRole, Credentials
from ocpi22.util import ModelUtilMixin
from ocpi22.ocpi_util import OcpiModule, Ocpi

# class ClientInfo(models.Model, ModelUtilMixin, OcpiModule):
#     """
#     This module provides parties connected to a hub with the connection status of other parties
#     that are connected to a hub that they can communicate with. So, CPOs know which eMSP and other
#     parties are online and vice versa.
#
#     Unlike the usual OCPI modules, this module is between eMSP/CPO and Hub instead of between eMSP and CPO.
#     """
#
#     ocpi_serializer_class = 'ocpi22.ocpi_api.api.ClientInfoSerializer'
#     ocpi_module_name = Ocpi.Modules.CLIENTINFO
#     ocpi_object_owner = 'HUB'
#     send_updates_to = ['EMSP', 'NAP', 'NSP', 'HUB', 'CPO', 'SCSP']
#
#     # The parties and roles found behind a single versions URL (Credentials.url)
#     credentials = models.OneToOneField(Credentials, on_delete=models.PROTECT, related_name='clientinfo')
#
#     # Status of the connection to the party.
#     status = models.CharField(max_length=9, choices=CONNECTION_STATUS_CHOICES)
#
#     # The OCPI field writable and maintained by object owner
#     last_updated = models.DateTimeField(null=True, blank=True)
#
#     def __str__(self):
#         return f'{self.credentials_role.country_code}*{self.credentials_role.party_id} {self.credentials_role.role} ' \
#                f'is {self.status} since {self.last_updated.strftime("%Y-%m-%dT%H:%M:%SZ")}'
#
#     def save(self, *args, **kwargs):
#         self.last_updated = timezone.now()
#         return super(self.__class__, self).save(*args, **kwargs)
