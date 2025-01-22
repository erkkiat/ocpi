import pytz
from django.utils.datetime_safe import datetime

import ocpi22.logging as logging

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.html import format_html
import util

from ocpi22.choices import OcpiModuleEnum, TOKEN_TYPE_CHOICES
from ocpi22.models import enum
from ocpi22.models.tariff import Tariff
from ocpi22.models.session import Session
from ocpi22.msp.account import check_balance
from ocpi22.util import format_cost, hours_minutes, ModelUtilMixin, CURRENCY_CHOICES
from ocpi22.ocpi.util import OcpiModule, Ocpi, generate_cdr_uid
from ocpiconnector.ocpi_identities import ocpi_platform

from django.utils.translation import gettext as _


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

    # The party responsible for the master data for this object
    # The country_code and party_id can be found through the CredentialsRole
    ocpi_master = models.ForeignKey(
        "ocpi22.CredentialsRole", related_name="cdrs", on_delete=models.PROTECT
    )

    # Uniquely identifies the CDR within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=39, db_index=True, verbose_name=_("UID"))

    # Start timestamp of the charging session, or in-case of a reservation
    # (before the start of a session) the start of the reservation.
    start_date_time = models.DateTimeField(verbose_name=_("Start date and time"))
    reservation_start_date_time = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Reservation start date and time")
    )

    # The timestamp when the session was completed/finished, charging might have finished before
    # the session ends, for example: EV is full, but parking cost also has to be paid.
    end_date_time = models.DateTimeField(verbose_name=_("End date and time"))

    # Unique ID of the Session for which this CDR is sent. Is only allowed to be omitted
    # when the CPO has not implemented the Sessions module or this CDR is the result of a reservation
    # that never became a charging session, thus no OCPI Session.
    session_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        blank=True,
        default="",
        verbose_name=_("Session ID"),
    )

    def session_url(self):
        return format_html(
            f'<a href="{util.reverse("session-by-id", args=[self.session_id])}">{self.session_id}</a>'
        )

    # Token used to start this charging session, includes all the relevant information to identify the unique token.
    cdr_token_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Token UID")
    )

    @property
    def token_id(self):
        return self.cdr_token_uid

    # Type of the token
    cdr_token_type = models.CharField(
        max_length=11, choices=TOKEN_TYPE_CHOICES, verbose_name=_("Token type")
    )

    # Uniquely identifies the EV driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    cdr_token_contract_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Token contract ID")
    )

    # Method used for authentication.
    auth_method = models.CharField(
        max_length=12,
        choices=enum.AUTH_METHOD_CHOICES,
        verbose_name=_("Authentication method"),
    )

    # Reference to the authorization given by the eMSP. When the eMSP provided an authorization_reference in either:
    # real-time authorization or StartSession, this field SHALL contain the same value.
    # When different authorization_reference values have been given by the eMSP that are relevant to this Session,
    # the last given value SHALL be used here.
    authorization_reference = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        blank=True,
        default="",
        verbose_name=_("Authorization reference"),
    )

    # Location where the charging session took place, including only the relevant EVSE and Connector.
    # Uniquely identifies the location within the CPO’s platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    cdr_location_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Location ID")
    )

    # Street/block name and house number if available.
    cdr_location_address = models.CharField(
        max_length=45, verbose_name=_("Location address")
    )

    # Display name of the location.
    cdr_location_name = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Location name")
    )

    # City or town.
    cdr_location_city = models.CharField(max_length=45, verbose_name=_("Location city"))

    # Postal code of the location.
    cdr_location_postal_code = models.CharField(
        max_length=10, blank=True, default="", verbose_name=_("Location postal code")
    )

    # State only to be used when relevant.
    cdr_location_state = models.CharField(
        max_length=20, blank=True, verbose_name=_("Location state")
    )

    # ISO 3166-1 alpha-3 code for the country of this location.
    cdr_location_country = models.CharField(
        max_length=3, verbose_name=_("Location country")
    )

    # Coordinates of the location.
    cdr_location_latitude = models.CharField(
        max_length=10, verbose_name=_("Location latitude")
    )
    cdr_location_longitude = models.CharField(
        max_length=11, verbose_name=_("Location longitude")
    )

    # Uniquely identifies the EVSE within the CPO’s platform (and suboperator platforms).
    # For example a database unique ID or the actual EVSE ID. This field can never be changed, modified or renamed.
    # This is the technical identification of the EVSE, not to be used as human readable identification,
    # use the field: evse_id for that.
    cdr_location_evse_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("EVSE UID")
    )

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects.".
    cdr_location_evse_id = models.CharField(max_length=48, verbose_name=_("EVSE ID"))

    @property
    def evse_id(self):
        return self.cdr_location_evse_id

    # Identifier of the connector within the EVSE.
    cdr_location_connector_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Connector ID")
    )

    # The standard of the installed connector.
    cdr_location_connector_standard = models.CharField(
        max_length=21,
        choices=Ocpi.STANDARD_CHOICES,
        verbose_name=_("Connector standard"),
    )

    # The format (socket/cable) of the installed connector.
    cdr_location_connector_format = models.CharField(
        max_length=6, choices=Ocpi.FORMAT_CHOICES, verbose_name=_("Connector format")
    )

    # The power type of the connector (AC/DC, phases)
    cdr_location_connector_power_type = models.CharField(
        max_length=16,
        choices=Ocpi.POWERTYPE_CHOICES_221,
        verbose_name=_("Connector power type"),
    )

    # Currency of the CDR in ISO 4217 Code.
    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, verbose_name=_("Currency")
    )

    # TODO: !!!!! ADD base_currency AND cost_in_base_currency

    # List of relevant Tariff Elements, see: Tariff. When relevant, a Free of Charge tariff
    # should also be in this list, and point to a defined Free of Charge Tariff.
    tariffs = models.ManyToManyField("Tariff", blank=True, verbose_name=_("Tariffs"))

    # Total sum of all the costs of this transaction in the specified currency.
    total_cost_excl_vat = models.FloatField(verbose_name=_("Total cost excl. VAT"))
    total_cost_incl_vat = models.FloatField(
        blank=True, null=True, verbose_name=_("Total cost incl. VAT")
    )

    # Total energy charged, in kWh.
    total_energy = models.FloatField(verbose_name=_("Total energy"))

    # Total duration of the charging session (including the duration of charging and not charging), in hours.
    @property
    def total_time(self) -> float:
        return round(
            (self.end_date_time - self.start_date_time).total_seconds() / 3600.0, 3
        )

    # When set to true, this is a Credit CDR, and the field credit_reference_id needs to be set as well.
    # Todo: Make a "create credit CDR" management command
    credit = models.BooleanField(default=False, verbose_name=_("Credit"))
    credit_reference = models.ForeignKey(
        "ocpi22.Cdr",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        verbose_name=_("Credit reference"),
    )

    # The party who will be billed for the transaction
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

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last updated")
    )

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_("Updated"))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Created"))

    def __str__(self):
        return (
            f"{self.end_date_time:%d.%m.%Y} - {self.cdr_token_uid} - "
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

    @classmethod
    def create_based_on_session(cls, session: Session):
        if not session.connector:
            logging.error(
                f"Not creating a CDR from Session {session.uid} since no Connector is specified"
            )
            return None
        # Was there already a CDR created for this Session?
        cdr = cls.objects.filter(session_id=session.uid)
        if cdr.exists():
            return cdr.first()
        if session.total_cost_excl_vat is None:
            logging.error(f"{settings.HOSTNAME}: Session {session} has no total cost")
        if not session.end_date_time:
            session.end_date_time = datetime.now(pytz.utc)

        cdr = cls.objects.create(
            uid=generate_cdr_uid(),
            start_date_time=session.start_date_time,
            end_date_time=session.end_date_time,
            session_id=session.uid,
            cdr_token_uid=session.cdr_token_uid,
            cdr_token_type=session.cdr_token_type,
            cdr_token_contract_id=session.cdr_token_contract_id,
            auth_method=session.auth_method,
            authorization_reference=session.authorization_reference,
            cdr_location_id=session.location.uid,
            cdr_location_address=session.location.address,
            cdr_location_name=session.location.name,
            cdr_location_city=session.location.city,
            cdr_location_postal_code=session.location.postal_code or "-",
            cdr_location_country=session.location.country,
            # Make sure coordinates have 6 decimals
            cdr_location_latitude=f"{float(session.location.latitude):.6f}",
            cdr_location_longitude=f"{float(session.location.longitude):.6f}",
            cdr_location_evse_uid=session.evse.uid,
            cdr_location_evse_id=session.evse.evse_id or "#NA",
            cdr_location_connector_id=session.connector.uid,
            cdr_location_connector_standard=session.connector.standard,
            cdr_location_connector_format=session.connector.format,
            cdr_location_connector_power_type=session.connector.power_type,
            currency=session.currency,
            total_cost_excl_vat=session.total_cost_excl_vat or 0.0,
            total_cost_incl_vat=session.total_cost_incl_vat or 0.0,
            total_energy=session.kwh,
            credentials=session.credentials,
            ocpi_master=session.ocpi_master,
            billed_to=session.billed_to,
            last_updated=datetime.now(pytz.utc),
        )

        tariffs = session.connector.tariff_ids.all()
        if tariffs.count():
            cdr_tariffs = Tariff.make_copies(tariffs)
        else:
            cdr_tariffs = Tariff.make_copies(
                Tariff.get_default_tariffs(session.connector.standard)
            )
        cdr.tariffs.set(cdr_tariffs)

        cdr.send_update_to_interested_parties(method="POST")

        return cdr

    @classmethod
    def session_changed(cls, instance: Session) -> None:
        if instance.status == Session.COMPLETED and instance.is_ours():
            if not Cdr.objects.filter(session_id=instance.uid).exists():
                Cdr.create_based_on_session(instance)

    def cost(self) -> str:
        return format_cost(
            self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency
        )

    @property
    def session(self) -> Session:
        return Session.get_if_exists(uid=self.session_id)


@receiver(post_save, sender=Session)
def session_post_save(sender, instance: Session, raw=None, *_args, **_kwargs):
    if not raw:  # Skip when installing test fixtures
        Cdr.session_changed(instance)
        if ocpi_platform.is_emsp:
            check_balance(instance)
