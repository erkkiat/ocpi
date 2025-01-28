from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from ocpi22.models.session import Session
from ocpi22.ocpi.util import Ocpi


class CdrLocation(models.Model):
    # Location where the charging session took place, including only the relevant EVSE and Connector.
    # Uniquely identifies the location within the CPO’s platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Location ID")
    )

    # Street/block name and house number if available.
    address = models.CharField(max_length=45, verbose_name=_("Location address"))

    # Display name of the location.
    name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Location name")
    )

    # City or town.
    city = models.CharField(max_length=45, verbose_name=_("Location city"))

    # Postal code of the location.
    postal_code = models.CharField(
        max_length=10, blank=True, default="", verbose_name=_("Location postal code")
    )

    # State only to be used when relevant.
    state = models.CharField(
        max_length=20, blank=True, verbose_name=_("Location state")
    )

    # ISO 3166-1 alpha-3 code for the country of this location.
    country = models.CharField(max_length=3, verbose_name=_("Location country"))

    # Coordinates of the location.
    latitude = models.CharField(max_length=10, verbose_name=_("Location latitude"))
    longitude = models.CharField(max_length=11, verbose_name=_("Location longitude"))

    # Uniquely identifies the EVSE within the CPO’s platform (and suboperator platforms).
    # For example a database unique ID or the actual EVSE ID. This field can never be changed, modified or renamed.
    # This is the technical identification of the EVSE, not to be used as human readable identification,
    # use the field: evse_id for that.
    evse_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("EVSE UID")
    )

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects.".
    evse_id = models.CharField(max_length=48, verbose_name=_("EVSE ID"))

    # Identifier of the connector within the EVSE.
    connector_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Connector ID")
    )

    # The standard of the installed connector.
    connector_standard = models.CharField(
        max_length=21,
        choices=Ocpi.STANDARD_CHOICES,
        verbose_name=_("Connector standard"),
    )

    # The format (socket/cable) of the installed connector.
    connector_format = models.CharField(
        max_length=6, choices=Ocpi.FORMAT_CHOICES, verbose_name=_("Connector format")
    )

    # The power type of the connector (AC/DC, phases)
    connector_power_type = models.CharField(
        max_length=16,
        choices=Ocpi.POWERTYPE_CHOICES_221,
        verbose_name=_("Connector power type"),
    )

    @classmethod
    def get_or_create_from_session(cls, session: Session):
        cdr_location, _created = cls.objects.get_or_create(
            id=session.location.id,
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
