from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
import util

from ocpi22.choices import OcpiModuleEnum, TOKEN_TYPE_CHOICES
from ocpi22.cpo.services import CdrService
from ocpi22.models import enum
from ocpi22.models.cdrlocation import CdrLocation
from ocpi22.models.session import Session
from ocpi22.util import format_cost, hours_minutes, ModelUtilMixin, CURRENCY_CHOICES
from ocpi22.ocpi.util import OcpiModule, Ocpi

from django.utils.translation import gettext_lazy as _


class Cdr(models.Model, ModelUtilMixin, OcpiModule):
    """
    A Charge Detail Record is the description of a concluded charging session.
    The CDR is the only billing-relevant object. CDRs are sent from the CPO to the eMSP
    after the charging session has ended. Although there is no requirement to send CDRs in (semi-) realtime,
    it is seen as good practice to send them as soon as possible. But if there is an agreement between
    parties to send them, for example, once a month, that is also allowed by OCPI.
    """

    ocpi_module_name = OcpiModuleEnum.CDRS
    ocpi_serializer_class = "ocpi22.ocpi.serializers.CdrSerializer"
    ocpi_object_owner = "CPO"
    send_updates_to = OcpiModule.INTERESTED_PARTIES
    update_method = "POST"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session_id"], name="session_id"),
        ]
        ordering = ("created",)
        verbose_name = _("Billing record")
        verbose_name_plural = _("Billing records")

    ocpi_master = models.ForeignKey(
        "ocpi22.CredentialsRole", related_name="cdrs", on_delete=models.PROTECT
    )

    uid = models.CharField(max_length=39, db_index=True, verbose_name=_("UID"))

    start_date_time = models.DateTimeField(verbose_name=_("Start date and time"))
    reservation_start_date_time = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Reservation start date and time")
    )

    end_date_time = models.DateTimeField(verbose_name=_("End date and time"))

    session_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        blank=True,
        default="",
        verbose_name=_("Session ID"),
    )

    cdr_token = models.ForeignKey(
        "ocpi22.CdrToken",
        null=True,
        on_delete=models.PROTECT,
        related_name="cdrs",
        verbose_name=_("CDR token"),
    )

    cdr_location = models.ForeignKey(
        CdrLocation,
        null=True,
        on_delete=models.PROTECT,
        related_name="cdrs",
        verbose_name=_("CDR location"),
    )

    cdr_token_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Token UID")
    )

    @property
    def token_id(self):
        return self.cdr_token.uid

    cdr_token_type = models.CharField(
        max_length=11, choices=TOKEN_TYPE_CHOICES, verbose_name=_("Token type")
    )

    cdr_token_contract_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Token contract ID")
    )

    auth_method = models.CharField(
        max_length=12,
        choices=enum.AUTH_METHOD_CHOICES,
        verbose_name=_("Authentication method"),
    )

    authorization_reference = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        blank=True,
        default="",
        verbose_name=_("Authorization reference"),
    )

    cdr_location_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Location ID")
    )

    @property
    def cdr_location_id(self):
        return self.cdr_location_uid

    @cdr_location_id.setter
    def cdr_location_id(self, value):
        self.cdr_location_uid = value

    cdr_location_address = models.CharField(
        max_length=45, verbose_name=_("Location address")
    )

    cdr_location_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Location name")
    )

    cdr_location_city = models.CharField(max_length=45, verbose_name=_("Location city"))

    cdr_location_postal_code = models.CharField(
        max_length=10, blank=True, default="", verbose_name=_("Location postal code")
    )

    cdr_location_state = models.CharField(
        max_length=20, blank=True, verbose_name=_("Location state")
    )

    cdr_location_country = models.CharField(
        max_length=3, verbose_name=_("Location country")
    )

    cdr_location_latitude = models.CharField(
        max_length=10, verbose_name=_("Location latitude")
    )
    cdr_location_longitude = models.CharField(
        max_length=11, verbose_name=_("Location longitude")
    )

    cdr_location_evse_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("EVSE UID")
    )

    cdr_location_evse_id = models.CharField(max_length=48, verbose_name=_("EVSE ID"))

    @property
    def evse_id(self):
        return self.cdr_location.evse_id

    cdr_location_connector_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Connector ID")
    )

    cdr_location_connector_standard = models.CharField(
        max_length=21,
        choices=Ocpi.STANDARD_CHOICES,
        verbose_name=_("Connector standard"),
    )

    cdr_location_connector_format = models.CharField(
        max_length=6, choices=Ocpi.FORMAT_CHOICES, verbose_name=_("Connector format")
    )

    cdr_location_connector_power_type = models.CharField(
        max_length=16,
        choices=Ocpi.POWERTYPE_CHOICES_221,
        verbose_name=_("Connector power type"),
    )

    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, verbose_name=_("Currency")
    )

    # TODO: !!!!! ADD base_currency AND cost_in_base_currency

    tariffs = models.ManyToManyField("Tariff", blank=True, verbose_name=_("Tariffs"))

    total_cost_excl_vat = models.FloatField(verbose_name=_("Total cost excl. VAT"))
    total_cost_incl_vat = models.FloatField(
        blank=True, null=True, verbose_name=_("Total cost incl. VAT")
    )

    total_energy = models.FloatField(verbose_name=_("Total energy"))

    @property
    def total_time(self) -> float:
        return round(
            (self.end_date_time - self.start_date_time).total_seconds() / 3600.0, 3
        )

    credit = models.BooleanField(default=False, verbose_name=_("Credit"))
    credit_reference = models.ForeignKey(
        "ocpi22.Cdr",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        verbose_name=_("Credit reference"),
    )

    billed_to = models.ForeignKey(
        "ocpi22.CredentialsRole",
        on_delete=models.PROTECT,
        related_name="billed_to_cdrs",
        null=True,
        blank=True,
        verbose_name=_("Billed to"),
    )

    credentials = models.ForeignKey(
        "ocpi22.Credentials",
        on_delete=models.PROTECT,
        null=True,
        related_name="cdrs",
        verbose_name=_("Credentials"),
    )

    @property
    def route_through_oicp(self):
        return self.session.route_through_oicp

    charging_periods = models.JSONField(null=True, verbose_name=_("Charging periods"))

    last_updated = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last updated")
    )

    updated = models.DateTimeField(auto_now=True, verbose_name=_("Updated"))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Created"))

    def __str__(self):
        return (
            f"{self.end_date_time:%d.%m.%Y} - {self.cdr_token.uid} - "
            f"{format_cost(self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency)} - "
            f"{hours_minutes(self.total_time)}"
        )

    def __hash__(self):
        return util.member_hash(self)

    def get_absolute_url(self, version=None):
        return util.reverse(
            "cdr-by-id",
            args=[
                version or "2.2.1",
                self.ocpi_master.country_code,
                self.ocpi_master.party_id,
                self.uid,
            ],
        )

    def total_cost(self):
        return (
            f'{"-" if self.credit else ""}'
            f'{format_cost(self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency)}'
            f'{" (credited)" if self.credit else ""}'
        )

    def total_session_time(self):
        return hours_minutes(self.total_time)

    def send_updates(self, data=None, method="post", path_components=[]) -> None:
        return self.send_update_to_interested_parties(
            method=method, path_components=path_components
        )

    @classmethod
    def session_changed(cls, instance: Session) -> None:
        if instance.status == Session.COMPLETED and instance.is_ours():
            if not Cdr.objects.filter(session_id=instance.uid).exists():
                CdrService.get_or_create_cdr(instance)

    def cost(self) -> str:
        return format_cost(
            self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency
        )

    @property
    def session(self) -> Session:
        return Session.get_if_exists(uid=self.session_id)

    @session.setter
    def session(self, value: Session | str):
        if isinstance(value, Session):
            self.session_id = value.uid
        elif isinstance(value, str):
            self.session_id = value
        raise TypeError(
            f"Session must be a Session object or a string, not '{type(value)}'"
        )


@receiver(post_save, sender=Session)
def session_post_save(sender, instance: Session, raw=None, *_args, **_kwargs):
    if not raw:  # Skip when installing test fixtures
        Cdr.session_changed(instance)
