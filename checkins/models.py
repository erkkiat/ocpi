from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext as _

from ocpi22.models.location import Connector


class Checkin(models.Model):
    connector = models.ForeignKey(
        Connector,
        related_name="checkins",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    # evse_id = models.CharField(max_length=48, blank=True, null=True)

    # name = models.CharField(max_length=255, blank=True, null=True)
    # address = models.CharField(max_length=45, blank=True, null=True)
    # city = models.CharField(max_length=45, blank=True, null=True)
    # postal_code = models.CharField(max_length=45, blank=True, null=True)
    # state = models.CharField(max_length=20, blank=True, null=True)
    #
    # # ISO 3166-1 alpha-3 code for the country of this location
    # country = models.CharField(max_length=3)
    #
    # latitude = models.FloatField()
    # longitude = models.FloatField()

    class StatusChoices(models.TextChoices):
        SUCCESS = "OK", _("Charging was successful")
        BLOCKED = "BL", _("Another vehicle is not charging, but blocks access")
        INOPERATIVE = "IN", _("Charge point seems inoperative")
        NO_AUTHORIZATION = (
            "AU",
            _("Charging is not authorized with my RFID or application"),
        )
        PREMATURE_STOP = "PR", _("Charging stopped prematurely")
        OTHER = "OT", _("Some other problem")

    datetime = models.DateTimeField()
    status = models.CharField(max_length=2, choices=StatusChoices.choices)
    comment = models.TextField(null=True, blank=True)

    original_json = models.JSONField("Original submission")

    source = models.ForeignKey(User, on_delete=models.PROTECT)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)
