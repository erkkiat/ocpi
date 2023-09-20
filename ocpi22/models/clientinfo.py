# class ClientInfo(models.Model, ModelUtilMixin, OcpiModule):
#     """
#     This module provides parties connected to a hub with the connection status of other parties
#     that are connected to a hub that they can communicate with. So, CPOs know which eMSP and other
#     parties are online and vice versa.
#
#     Unlike the usual OCPI modules, this module is between eMSP/CPO and Hub instead of between eMSP and CPO.
#     """
#
#     ocpi_serializer_class = 'ocpi22.ocpi.api.ClientInfoSerializer'
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
#                f'is {self.status} since {self.last_updated.strftime(settings.OCPI_DATE_FORMAT)}'
#
#     def save(self, *args, **kwargs):
#         self.last_updated = datetime.utcnow().replace(tzinfo=pytz.utc)
#         return super(self.__class__, self).save(*args, **kwargs)
