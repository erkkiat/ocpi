from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from ocpi22.choices import TOKEN_TYPE_CHOICES


class CdrToken(models.Model):
    ocpi_master = models.ForeignKey("ocpi22.CredentialsRole", on_delete=models.PROTECT)

    uid = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)

    token_type = models.CharField(
        max_length=11, choices=TOKEN_TYPE_CHOICES, verbose_name=_("Token type")
    )

    contract_id = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)

    def __str__(self):
        return f'{str(self.ocpi_master)} / ID "{self.uid}" / contract: "{self.contract_id}"'
