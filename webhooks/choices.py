from django.db import models
from django.utils.translation import gettext_noop as _


class WebhookType(models.TextChoices):
    INVOICING = "INVOICING", _("Invoicing")
    TOKEN_AUTHORIZATION = "TOKEN_AUTH", _("Token authorization")
    CHARGEPOINT_STATUS = "CP_STATUS", _("Charge point status")
    REMOTE_COMMAND = "REMOTE_COMMAND", _("Remote command")
    TERMINAL = "TERMINAL", _("Terminal")
    FINANCIAL_ADVICE_CONFIRMATION = "FAC", _("Financial advice confirmation")


class RemoteCommandType(models.TextChoices):
    CANCEL_RESERVATION = "CANCEL_RESERVATION", _("Cancel Reservation")
    RESERVE_NOW = "RESERVE_NOW", _("Reserve Now")
    START_SESSION = "START_SESSION", _("Start Session")
    STOP_SESSION = "STOP_SESSION", _("Stop Session")
    UNLOCK_CONNECTOR = "UNLOCK_CONNECTOR", _("Unlock Connector")
