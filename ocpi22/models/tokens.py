from django.utils.datetime_safe import datetime

import pytz
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

import util
from ocpi22 import choices

from ocpi22.choices import OcpiModuleEnum
from ocpi22.util import ModelUtilMixin
from ocpi22.ocpi.util import OcpiModule
from ocpiconnector.manager import PartnerManager


class Token(models.Model, ModelUtilMixin, OcpiModule):
    """
    A Token structure with data owned by the eMSP
    """

    class Meta:
        verbose_name = _("token")
        verbose_name_plural = _("tokens")
        permissions = [
            (
                "charge_with_any_token",
                "Can start and stop charging with any token ID (even if it's not in the database)",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["uid", "ocpi_master"], name="unique_token_uid_per_ocpimaster"
            )
        ]
        indexes = [
            models.Index(fields=["uid", "ocpi_master"]),
        ]

    ocpi_serializer_class = "ocpi22.ocpi.serializers.TokenSerializer"
    ocpi_module_name = OcpiModuleEnum.TOKENS
    ocpi_object_owner = "EMSP"
    send_updates_to = ("CPO", "HUB")

    objects = PartnerManager()

    SENDER = None

    upper_case_fields = ("uid", "contract_id", "language")

    ocpi_master = models.ForeignKey(
        "ocpi22.CredentialsRole",
        related_name="tokens",
        null=True,
        on_delete=models.PROTECT,
    )

    uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("UID")
    )

    type = models.CharField(
        max_length=11,
        choices=choices.TOKEN_TYPE_CHOICES,
        default="RFID",
        verbose_name=_("Type"),
    )

    contract_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Contract ID")
    )

    visual_number = models.CharField(
        max_length=64, null=True, blank=True, verbose_name=_("Visual number")
    )

    issuer = models.CharField(max_length=64, verbose_name=_("Issuer"))

    group_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        null=True,
        blank=True,
        verbose_name=_("Group ID"),
    )

    valid = models.BooleanField(default=True, verbose_name=_("Valid"))

    ALWAYS = "ALWAYS"
    ALLOWED = "ALLOWED"
    ALLOWED_OFFLINE = "ALLOWED_OFFLINE"
    NEVER = "NEVER"

    WHITELIST_CHOICES = (
        (ALWAYS, "Always"),
        (ALLOWED, "Allowed"),
        (ALLOWED_OFFLINE, "Allowed when offline"),
        (NEVER, "Never, only real time"),
    )
    whitelist = models.CharField(
        max_length=15, choices=WHITELIST_CHOICES, verbose_name=_("Whitelist")
    )

    language = models.CharField(
        max_length=2,
        null=True,
        choices=choices.LANGUAGE_CHOICES.sort(key=lambda x: x[1]),
        verbose_name=_("Language"),
    )

    PROFILE_TYPE_CHOICES = (
        (
            "CHEAP",
            "Cheap charging",
        ),  # Driver wants to use the cheapest charging profile possible.
        (
            "FAST",
            "Fast charging",
        ),  # Driver wants his EV charged as quickly as possible and is willing to pay a premium for this.
        (
            "GREEN",
            "Green energy",
        ),  # Driver wants his EV charged with as much regenerative (green) energy as possible.
        (
            "REGULAR",
            "Regular, no preference",
        ),  # Driver does not have special preferences.
    )
    default_profile_type = models.CharField(
        max_length=7,
        null=True,
        blank=True,
        choices=PROFILE_TYPE_CHOICES,
        verbose_name=_("Default profile type"),
    )

    last_updated = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last updated")
    )

    updated = models.DateTimeField(auto_now=True, verbose_name=_("Updated"))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Created"))

    customer = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="tokens",
        verbose_name=_("Customer"),
    )

    def __str__(self):
        return f"{self.party_str()}: {self.type} {self.uid}"

    def __hash__(self):
        return util.member_hash(self)

    def get(self, key, default=None):
        """Mimic a dict, so that we can use the same code for Token and AdhocToken as well as dicts and OrderedDicts"""
        return getattr(self, key, default)

    @property
    def owner(self):
        return self.ocpi_master.get_party()

    def save(self, *args, raw=False, **kwargs):
        """
        Save the Token object to the database.
        @param args:
        @param raw: Is loaddata loading fixtures for unittest
        @param kwargs:
        @return:
        """
        self.change_fields_to_upper_case()
        if self.is_ours() and not raw:
            self.last_updated = datetime.now(pytz.utc)
        return super(self.__class__, self).save(*args, **kwargs)

    def get_absolute_url(self, version=None):
        if not self.ocpi_master:
            return ""
        return util.reverse(
            "token-by-id",
            args=[
                version or "2.2.1",
                self.ocpi_master.country_code,
                self.ocpi_master.party_id,
                self.uid,
            ],
        )

    def total_balance_float(self) -> float:
        if self.customer:
            return sum([account.balance for account in self.customer.accounts.all()])
        return 0.0

    def balances(self) -> str:
        # For TokenAdmin list view
        if not self.customer:
            return "-"
        return format_html(
            ", ".join(
                [
                    f"{account.balance}{account.currency}<br>"
                    for account in self.customer.accounts.all()
                ]
            )
        )
