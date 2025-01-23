from django.db import models
from django.utils.translation import gettext_lazy as _


class AuthMethodChoices(models.TextChoices):
    """
    Enum for the OCPI authorization methods
    """

    AUTH_REQUEST = "AUTH_REQUEST", _("Authentication request to eMSP")
    COMMAND = "COMMAND", _("Command from eMSP")
    WHITELIST = "WHITELIST", _("Token on whitelist")


AUTH_METHOD_CHOICES = [(key, value) for key, value in AuthMethodChoices.choices]
