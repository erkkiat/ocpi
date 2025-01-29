from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from ocpi22.choices import TOKEN_TYPE_CHOICES


class CdrToken(models.Model):
    # The identity of the eMSP which owns this Token.
    ocpi_master = models.ForeignKey("ocpi22.CredentialsRole", on_delete=models.PROTECT)

    # Token used to start this charging session, including all the relevant information to identify the unique token.
    # Unique ID by which this Token can be identified.
    # This is the field used by the CPO’s system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a type=APP_USER Token, it will be a unique, by the eMSP, generated ID.
    uid = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)

    token_type = models.CharField(
        max_length=11, choices=TOKEN_TYPE_CHOICES, verbose_name=_("Token type")
    )

    # Uniquely identifies the EV driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    contract_id = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH)

    def __str__(self):
        return f'{str(self.ocpi_master)} / ID "{self.uid}" / contract: "{self.contract_id}"'
