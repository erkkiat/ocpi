from django.db import models
from django.utils.translation import gettext_noop as _


class WebhookEventChoices(models.TextChoices):
    INVOICING = "INVOICING", _("Invoicing")
    SESSION = "SESSION", _("Session")
    TOKEN_AUTHORIZATION = "TOKEN_AUTH", _("Token authorization")
    CHARGEPOINT_STATUS = "CP_STATUS", _("Charge point status")
