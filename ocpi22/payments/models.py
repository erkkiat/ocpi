"""
EVRF DirectPayment Module Models

This module implements the DirectPayment OCPI 2.2.1 extension from EV Roaming Foundation.
It supports direct payment at EV charging stations via payment terminals (e.g., Payter).

Reference: DirectPayment_2_2_1___EVRF_version.pdf (March 2024)
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from generic.validators import (
    validate_country_code_alpha2,
    validate_country_code_alpha3,
    validate_latitude,
    validate_longitude,
)


class InvoiceCreatorEnum(models.TextChoices):
    CPO = "CPO", _("Charge Point Operator")
    PTP = "PTP", _("Payment Terminal Provider")


class Terminal(models.Model):
    """
    Payment terminal that can handle EV charging transactions.

    Ownership: PTP (Payment Terminal Provider, e.g., Payter)
    Flow:
        1. PTP POSTs terminal with terminal_id and customer_reference
        2. CPO stores it and later PATCH/PUT location assignments back to PTP
        3. PTP can then start sessions on assigned locations via Commands module

    Reference: EVRF DirectPayment spec Section 5.1
    """

    class Meta:
        app_label = "ocpi22"
        db_table = "ocpi22_terminal"
        verbose_name = _("Payment Terminal")
        verbose_name_plural = _("Payment Terminals")
        indexes = [
            models.Index(fields=["terminal_id"], name="ocpi22_term_termina_idx"),
            models.Index(fields=["customer_reference"], name="ocpi22_term_custome_idx"),
            models.Index(fields=["last_updated"], name="ocpi22_term_last_up_idx"),
            models.Index(
                fields=["credentials", "last_updated"],
                name="ocpi22_term_cred_last_idx",
            ),
            models.Index(
                fields=["country_code", "party_id"],
                name="ocpi22_term_cc_party_idx",
            ),
        ]

    terminal_id = models.CharField(
        max_length=36,
        unique=True,
        db_index=True,
        verbose_name=_("Terminal ID"),
        help_text=_("Unique ID that identifies a terminal"),
    )

    customer_reference = models.CharField(
        max_length=36,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_("Customer Reference"),
        help_text=_("Reference sent by PTP to link terminal to CSMS/contract"),
    )

    party_id = models.CharField(
        max_length=3,
        blank=True,
        null=True,
        verbose_name=_("Party ID"),
        help_text=_("Alternative to customer_reference"),
    )
    country_code = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        validators=[validate_country_code_alpha2],
        verbose_name=_("Country Code"),
        help_text=_(
            "ISO 3166-1 alpha-2 country code. Alternative to customer_reference"
        ),
    )

    address = models.CharField(
        max_length=45,
        blank=True,
        null=True,
        verbose_name=_("Address"),
        help_text=_("Street/block name and house number"),
    )
    city = models.CharField(
        max_length=45,
        blank=True,
        null=True,
        verbose_name=_("City"),
        help_text=_("City or town"),
    )
    postal_code = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        verbose_name=_("Postal Code"),
        help_text=_("Postal code of the terminal"),
    )
    state = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("State"),
        help_text=_("State or province"),
    )
    country = models.CharField(
        max_length=3,
        blank=True,
        null=True,
        validators=[validate_country_code_alpha3],
        verbose_name=_("Country"),
        help_text=_("ISO 3166-1 alpha-3 country code"),
    )

    latitude = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        validators=[validate_latitude],
        verbose_name=_("Latitude"),
    )
    longitude = models.CharField(
        max_length=11,
        blank=True,
        null=True,
        validators=[validate_longitude],
        verbose_name=_("Longitude"),
    )

    invoice_base_url = models.URLField(
        blank=True,
        null=True,
        verbose_name=_("Invoice Base URL"),
        help_text=_(
            "Base URL to downloadable invoice. "
            "Full URL: {invoice_base_url}/{authorization_reference}"
        ),
    )
    invoice_creator = models.CharField(
        max_length=3,
        choices=InvoiceCreatorEnum.choices,
        blank=True,
        null=True,
        verbose_name=_("Invoice Creator"),
        help_text=_("Which party creates the invoice for the EV driver"),
    )

    locations = models.ManyToManyField(
        "ocpi22.Location",
        blank=True,
        related_name="payment_terminals",
        verbose_name=_("Assigned Locations"),
        help_text=_("Locations this terminal can start sessions on"),
        db_table="ocpi22_terminal_locations",
    )
    evses = models.ManyToManyField(
        "ocpi22.Evse",
        blank=True,
        related_name="payment_terminals",
        verbose_name=_("Assigned EVSEs"),
        help_text=_(
            "Specific EVSEs this terminal can start sessions on. "
            "Optional - for finer control than location-level assignment."
        ),
        db_table="ocpi22_terminal_evses",
    )

    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Last Updated"),
        help_text=_("Timestamp when this Terminal was last updated (or created)"),
    )

    created = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created"),
    )
    updated = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated"),
    )

    credentials = models.ForeignKey(
        "ocpi22.Credentials",
        on_delete=models.PROTECT,
        related_name="payment_terminals",
        null=True,
        blank=True,
        verbose_name=_("PTP Credentials"),
        help_text=_("Credentials of the PTP (e.g., Payter) that owns this terminal."),
    )

    def __str__(self) -> str:
        if self.customer_reference:
            return f"Terminal {self.terminal_id} ({self.customer_reference})"
        return f"Terminal {self.terminal_id}"

    def clean(self) -> None:
        super().clean()
        if self.country_code:
            validate_country_code_alpha2(self.country_code)
        if self.country:
            validate_country_code_alpha3(self.country)
        if self.latitude:
            validate_latitude(self.latitude)
        if self.longitude:
            validate_longitude(self.longitude)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    @property
    def coordinates(self) -> dict[str, str] | None:
        if self.latitude and self.longitude:
            return {"latitude": self.latitude, "longitude": self.longitude}
        return None

    @property
    def location_ids(self) -> list[str]:
        return list(self.locations.values_list("uid", flat=True))

    @property
    def evse_uids(self) -> list[str]:
        return list(self.evses.values_list("uid", flat=True))
