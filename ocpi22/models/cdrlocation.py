from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from ocpi22.models.session import Session
from ocpi22.ocpi.util import Ocpi


class CdrLocation(models.Model):
    uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Location ID")
    )

    address = models.CharField(max_length=45, verbose_name=_("Location address"))

    name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Location name")
    )

    city = models.CharField(max_length=45, verbose_name=_("Location city"))

    postal_code = models.CharField(
        max_length=10, blank=True, default="", verbose_name=_("Location postal code")
    )

    state = models.CharField(
        max_length=20, blank=True, verbose_name=_("Location state")
    )

    country = models.CharField(max_length=3, verbose_name=_("Location country"))

    latitude = models.CharField(max_length=10, verbose_name=_("Location latitude"))
    longitude = models.CharField(max_length=11, verbose_name=_("Location longitude"))

    evse_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("EVSE UID")
    )

    evse_id = models.CharField(max_length=48, verbose_name=_("EVSE ID"))

    connector_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Connector ID")
    )

    connector_standard = models.CharField(
        max_length=21,
        choices=Ocpi.STANDARD_CHOICES,
        verbose_name=_("Connector standard"),
    )

    connector_format = models.CharField(
        max_length=6, choices=Ocpi.FORMAT_CHOICES, verbose_name=_("Connector format")
    )

    connector_power_type = models.CharField(
        max_length=16,
        choices=Ocpi.POWERTYPE_CHOICES_221,
        verbose_name=_("Connector power type"),
    )

    @classmethod
    def get_or_create_from_session(cls, session: Session):
        cdr_location, _created = cls.objects.get_or_create(
            uid=session.location.uid,
            name=session.location.name,
            address=session.location.address,
            city=session.location.city,
            postal_code=session.location.postal_code,
            state=session.location.state,
            country=session.location.country,
            # Make sure coordinates have 6 decimals
            latitude=f"{float(session.location.latitude):.6f}",
            longitude=f"{float(session.location.longitude):.6f}",
            evse_uid=session.evse.uid,
            evse_id=session.evse.evse_id,
            connector_id=session.connector.uid,
            connector_standard=session.connector.standard,
            connector_format=session.connector.format,
            connector_power_type=session.connector.power_type,
        )
        return cdr_location

    def __str__(self):
        return f'"{self.name or "N/A"}" at {self.address}, {self.city}, {self.country}'
