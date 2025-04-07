from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _

from ocpi22.models.session import Session

PHONE_FIELD_LENGTH = 20


class Profile(models.Model):
    user = models.OneToOneField(
        User, related_name="profile", on_delete=models.CASCADE, primary_key=True
    )
    phone = models.CharField(max_length=PHONE_FIELD_LENGTH, blank=True)


class OCPITokenField(models.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.pop("max_length", None)
        super().__init__(*args, max_length=settings.OCPI_22_MAX_UID_LENGTH, **kwargs)


class Authorization(models.Model):
    authorization_reference = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        blank=True,
        db_index=True,
        default="",
        verbose_name=_("Authorization reference"),
    )
    session = models.OneToOneField(
        Session,
        related_name="authorization",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Session"),
    )
    max_price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name=_("Max price"),
    )

    # This can be an RFID or an app token, the latter not having a database instance to foreign key to
    token_uid = OCPITokenField(
        verbose_name=_("Token UID"),
        null=True,
        help_text="The token UID, either an RFID or an app token (not the Token.pk)",
    )

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_("Updated"))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Created"))

    def __str__(self):
        session_str = self.session.uid if self.session else ""
        return f"{self.authorization_reference} - {self.max_price} - {session_str}"
