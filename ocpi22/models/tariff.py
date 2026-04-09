import uuid
from copy import deepcopy
from django.utils.translation import gettext_lazy as _, gettext
from typing import Optional

import pytz
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import QuerySet
from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from django.utils.datetime_safe import datetime
from django.utils.html import format_html
from multiselectfield import MultiSelectField
import util

from ocpi22 import choices, ocpi_logging as logging
from ocpi22.choices import OcpiModuleEnum, OcpiRolesEnum, DYNAMIC_PRICE_SOURCE_CHOICES
from ocpi22.credentials.util import find_endpoints_by_roles
import ocpi22.tasks as tasks
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.displaytext import DisplayText
from ocpi22.util import (
    ModelUtilMixin,
    format_currency,
    CURRENCY_CHOICES,
    hours_minutes,
    build_absolute_uri,
)
from ocpi22.ocpi.util import OcpiModule, Ocpi
from ocpiconnector.manager import PartnerManager
from ocpiconnector.ocpi_identities import get_our_party, ocpi_platform
from ocpiconnector.util import (
    weekday_range_to_str,
    humanize_time,
    humanize_date_range,
    build_item_url,
)


# Todo: Minimum amount to be billed. This unit will be billed in this step_size blocks.
#  Amounts that are less then this step_size are rounded up to the given step_size.
#  For example: if type is TIME and step_size has a value of 300, then time will be billed in blocks of 5 minutes.
#  If 6 minutes were used, 10 minutes (2 blocks of step_size) will be billed.


# Tariff is an immutable model
class Tariff(models.Model, ModelUtilMixin, OcpiModule):
    ocpi_serializer_class = "ocpi22.ocpi.api.TariffSerializer"
    ocpi_module_name = OcpiModuleEnum.TARIFFS
    ocpi_object_owner = "CPO"
    send_updates_to = ("EMSP", "NAP", "NSP", "HUB", "OTHER")

    objects = PartnerManager()

    class Meta:
        verbose_name = _("tariff")
        verbose_name_plural = _("tariffs")
        # constraints = [  # Cannot constrain because there will be archived Tariffs with the same uid and ocpi_master
        #     models.UniqueConstraint(fields=['uid', 'ocpi_master'], name='unique_tariff_uid_per_ocpimaster')
        # ]
        indexes = [models.Index(fields=["uid", "ocpi_master", "archived"])]

    # MySQL didn't support Q-conditions
    # class Meta:
    #     constraints = [
    #         models.UniqueConstraint(
    #             # Allow only one Tariff to be active for each party & uid combination
    #             fields=['country_code', 'party_id', 'uid'],
    #             condition=Q(archived=True),
    #             name='limit_one_tariff_per_uid_party_not_archived'
    #         ),
    #     ]

    upper_case_fields = ("currency", "uid")

    # This object has been archived, but there may be references to it
    archived = models.BooleanField(default=False, verbose_name=_("Archived"))

    # The party responsible for the master data for this object
    # The country_code and party_id can be found through the CredentialsRole
    ocpi_master = models.ForeignKey(
        "ocpi22.CredentialsRole", related_name="tariffs", on_delete=models.PROTECT
    )

    # Uniquely identifies the tariff within the CPO’s platform (and suboperator platforms)
    uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True, verbose_name=_("UID")
    )

    # ISO-4217 code of the currency of this tariff
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default=settings.DEFAULT_CURRENCY,
        verbose_name=_("Currency"),
    )

    # Defines the type of the tariff. This allows for distinction in case of given Charging Preferences.
    # When omitted, this tariff is valid for all sessions.
    TYPE_CHOICES = (
        # Used to describe that a Tariff is valid when ad-hoc payment is used at
        # the Charge Point (for example: Debit or Credit card payment terminal).
        ("AD_HOC_PAYMENT", _("Ad hoc payment")),
        # Used to describe that a Tariff is valid when Charging Preference: CHEAP is set for the session.
        ("PROFILE_CHEAP", _("CHEAP profile")),
        # Used to describe that a Tariff is valid when Charging Preference: FAST is set for the session.
        ("PROFILE_FAST", _("FAST profile")),
        # Used to describe that a Tariff is valid when Charging Preference: GREEN is set for the session.
        ("PROFILE_GREEN", _("GREEN profile")),
        # Used to describe that a Tariff is valid when using an RFID, without any Charging Preference,
        # or when Charging Preference: REGULAR is set for the session.
        ("REGULAR", _("Regular profile")),
    )

    type = models.CharField(
        max_length=14,
        choices=TYPE_CHOICES,
        blank=True,
        default="",
        verbose_name=_("type"),
    )

    # URL to a web page that contains an explanation of the tariff information in human readable form.
    tariff_alt_url = models.URLField(
        blank=True, default="", verbose_name=_("Tariff alternative URL")
    )

    tariff_alt_text = models.ManyToManyField(
        DisplayText, blank=True, related_name="tariffs"
    )

    # When this field is set, a Charging Session with this tariff will at least cost this amount.
    # This is different from a FLAT fee (Start Tariff, Transaction Fee), as a FLAT fee is a fixed
    # amount that has to be paid for any Charging Session. A minimum price indicates that when
    # the cost of a Charging Session is lower than this amount, the cost of the Session will be
    # equal to this amount.
    min_price_excl_vat = models.FloatField(
        null=True, blank=True, verbose_name=_("minimum price excluding tax")
    )
    min_price_incl_vat = models.FloatField(
        null=True, blank=True, verbose_name=_("minimum price including tax")
    )

    max_price_excl_vat = models.FloatField(
        null=True, blank=True, verbose_name=_("Maximum price excluding tax")
    )
    max_price_incl_vat = models.FloatField(
        null=True, blank=True, verbose_name=_("Maximum price including tax")
    )

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last updated")
    )

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_("Updated"))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Created"))

    def __str__(self):
        return self.uid

    def __hash__(self):
        return util.member_hash(self)

    def min_and_max_price(self) -> str:
        result = ""
        if self.min_price_incl_vat or self.min_price_excl_vat:
            result = (
                f", min {format_currency(self.min_price_incl_vat, self.currency) or '-'} "
                f"({format_currency(self.min_price_excl_vat, self.currency) or '-'} VAT 0%)"
            )
        if self.max_price_incl_vat or self.max_price_excl_vat:
            result += (
                f", max {format_currency(self.max_price_incl_vat, self.currency) or '-'} "
                f"({format_currency(self.max_price_excl_vat, self.currency) or '-'} VAT 0%)"
            )
        return result

    def price(self) -> str:
        """Format the price components in a readable form"""
        components = [
            str(pc) for pc in [element for element in self.tariff_elements.all()]
        ]
        return f"{', '.join(components or [f'{self.uid}'])}{self.min_and_max_price()}"

    def link(self):
        url = util.reverse("admin:ocpi22_tariff_change", args=[self.pk])
        return format_html(f"<a href='{url}'>{self.price()}</a>")

    def get_absolute_url(self, version=None):
        # Todo: Move this to one of the OCPI utility classes
        return util.reverse(
            "tariff-by-id",
            args=[
                version or "2.2.1",
                self.ocpi_master.country_code,
                self.ocpi_master.party_id,
                self.uid,
            ],
        )

    def get_admin_url(self):
        return build_absolute_uri(
            util.reverse("admin:ocpi22_tariff_change", args=(self.pk,))
        )

    @property
    def name(self) -> str:
        return str(self.uid)

    @classmethod
    def make_copy(cls, tariff):
        elements = tariff.tariff_elements.all()
        new_tariff = deepcopy(tariff)
        new_tariff.pk = None
        new_tariff.archived = True
        new_tariff.save()

        for e in elements:
            price_components = e.price_components.all().select_related()
            e.pk = None
            e.tariff = new_tariff
            e.save()

            for pc in price_components:
                pc.pk = None
                pc.tariff_element = e
                pc.save()

        return new_tariff

    @classmethod
    def get_default_tariffs(cls, standard) -> QuerySet:
        try:
            default_tariffs = DefaultTariffs.objects.get(standard=standard)
            return default_tariffs.tariffs.all()
        except DefaultTariffs.DoesNotExist:
            return DefaultTariffs.objects.none()

    def get_type(self, tariff_type: str) -> Optional[object]:
        for te in self.tariff_elements.all():
            pc: PriceComponent
            for pc in te.price_components.all():
                if pc.type == tariff_type:
                    return pc
        return None

    def save(self, *args, raw=False, **kwargs):
        """
        Save the Tariff object to the database.
        @param args:
        @param raw: Is loaddata loading fixtures for unittest
        @param kwargs:
        @return:
        """
        self.change_fields_to_upper_case()
        if self.is_ours() and not raw:
            self.last_updated = datetime.now(pytz.utc)
        return super().save(*args, **kwargs)


class TariffElement(models.Model, ModelUtilMixin):
    start_time = models.TimeField(
        null=True, blank=True, help_text=_("This is in charger local time")
    )
    end_time = models.TimeField(
        null=True, blank=True, help_text=_("This is in charger local time")
    )

    start_date = models.DateField(
        null=True, blank=True, help_text=_("This is in charger local time")
    )
    end_date = models.DateField(
        null=True, blank=True, help_text=_("This is in charger local time")
    )

    min_kwh = models.FloatField(null=True, blank=True)
    max_kwh = models.FloatField(null=True, blank=True)

    min_current = models.FloatField(null=True, blank=True)
    max_current = models.FloatField(null=True, blank=True)

    min_power = models.FloatField(null=True, blank=True)
    max_power = models.FloatField(null=True, blank=True)

    min_duration = models.IntegerField(null=True, blank=True)
    max_duration = models.IntegerField(null=True, blank=True)

    DAY_OF_WEEK_CHOICES = (
        ("MONDAY", _("Monday")),
        ("TUESDAY", _("Tuesday")),
        ("WEDNESDAY", _("Wednesday")),
        ("THURSDAY", _("Thursday")),
        ("FRIDAY", _("Friday")),
        ("SATURDAY", _("Saturday")),
        ("SUNDAY", _("Sunday")),
    )

    day_of_week = MultiSelectField(
        max_length=56, null=True, blank=True, choices=DAY_OF_WEEK_CHOICES
    )

    reservation = models.CharField(
        max_length=19, null=True, blank=True, choices=choices.RESERVATION_CHOICES
    )

    tariff = models.ForeignKey(
        Tariff, related_name="tariff_elements", on_delete=models.CASCADE
    )

    def weekday_numbers(self) -> tuple:
        if not self.day_of_week:
            return tuple()
        return tuple(
            map(lambda x: choices.DAY_OF_WEEK_NUMBERS.get(x), list(self.day_of_week))
        )

    def restrictions_str(self):
        days_of_week_str = weekday_range_to_str(self.weekday_numbers())
        times = (
            f" {humanize_time(self.start_time)}-{humanize_time(self.end_time)}"
            if self.start_time
            else ""
        )
        validity = ""
        if self.start_date or self.end_date:
            validity = gettext(" (valid {date_range}").format(
                date_range=humanize_date_range(self.start_date, self.end_date)
            )
        return (
            f" ({days_of_week_str}{times}){validity}"
            if days_of_week_str
            else gettext(" (during {times})".format(times=times))
            if times
            else ""
        )

    def __str__(self):
        result = " + ".join([str(pc) for pc in self.price_components.all()])
        return f"{result}{self.restrictions_str()}"


class PriceComponent(models.Model, ModelUtilMixin):
    # List of price components that describe the pricing of a tariff.

    TYPE_CHOICES = (
        # Defined in kWh, step_size multiplier: 1 Wh
        ("ENERGY", _("kWh")),
        # Flat fee without unit for step_size
        ("FLAT", _("Flat")),
        # Time not charging: defined in hours, step_size multiplier: 1 second
        ("PARKING_TIME", _("Parking per hour")),
        # Todo: Implement PARKING_TIME PriceComponent
        # Todo: How to prevent people from stopping session on app without disconnecting?
        # Time charging: defined in hours, step_size multiplier: 1 second
        # Can also be used in combination with a RESERVATION restriction to describe the price of the reservation time.
        ("TIME", _("Charging per hour")),
    )
    type = models.CharField(max_length=12, choices=TYPE_CHOICES)

    # Price /unit (excl. VAT) for this tariff dimension.
    price = models.DecimalField(
        max_digits=12, decimal_places=6, verbose_name=_("Price excluding tax")
    )

    # Applicable VAT percentage for this tariff dimension. If omitted, no VAT is applicable.
    # Not providing a VAT is different from 0% VAT, which would be a value of 0.0 here.
    vat = models.DecimalField(blank=True, null=True, max_digits=8, decimal_places=4)

    # Minimum amount to be billed. This unit will be billed in this step_size blocks.
    # Amounts that are less then this step_size are rounded up to the given step_size.
    # For example: if type is TIME and step_size has a value of 300, then time will be billed in blocks of 5 minutes.
    # If 6 minutes were used, 10 minutes (2 blocks of step_size) will be billed.
    step_size = models.IntegerField()

    # Connect this price component to a dynamic price source, which will overwrite price and set type='ENERGY'
    dynamic_price_source = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        choices=DYNAMIC_PRICE_SOURCE_CHOICES,
        help_text="Connect this price component to a dynamic price source, "
        "which will get the hourly or daily price from a source and set type='ENERGY'.",
    )

    @property
    def tariff(self):
        return self.tariff_element.tariff

    tariff_element = models.ForeignKey(
        TariffElement, related_name="price_components", on_delete=models.CASCADE
    )

    def _format_step_and_type(self, tariff_type=None, step_size=None):
        """
        >>> s = PriceComponent()
        >>> s._format_step_and_type('ENERGY', 1)
        '/kWh'
        >>> s._format_step_and_type('ENERGY', 1000)
        '/kWh'
        >>> s._format_step_and_type('FLAT', 1)
        ' flat'
        >>> s._format_step_and_type('TIME', 1)
        '/h'
        """
        t = tariff_type or self.type
        return {
            "ENERGY": _("/kWh"),
            "FLAT": _(" flat"),
            "TIME": _("/h"),
            "PARKING_TIME": _("/h parking"),
        }.get(t, "")

    def _format_duration(self):
        result = ""
        e: TariffElement = self.tariff_element
        if e.min_duration:
            result += f" after {hours_minutes(e.min_duration / 3600)}"
        if e.max_duration:
            result += f" until {hours_minutes(e.max_duration / 3600)}"
        return result

    def __str__(self):
        return (
            f"{format_currency(self.price or 0.0, self.tariff.currency)}"
            f"{self._format_step_and_type()}{self._format_duration()}"
        )


class DefaultTariffs(models.Model):
    class Meta:
        verbose_name_plural = "default tariffs"

    standard = models.CharField(
        max_length=21, choices=Ocpi.STANDARD_CHOICES, unique=True
    )
    tariffs = models.ManyToManyField(Tariff, related_name="default_standards")

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f"{self.get_standard_display()} defaults to tariffs {', '.join(str(t) for t in self.tariffs.all())}"

    def tariff_list(self):
        return f"{', '.join(str(t) for t in self.tariffs.all())}"


@receiver(pre_save, sender=Tariff)
def tariff_pre_save(sender, instance, *_args, raw, **_kwargs):
    if raw:
        return
    tariff: Tariff = instance
    if not tariff.uid:
        tariff.uid = uuid.uuid4().hex


@receiver(post_save, sender=PriceComponent)
def price_component_post_save(sender, instance: PriceComponent, *_args, raw, **_kwargs):
    tariff = instance.tariff
    # Do not update last_updated here, only owner does that
    tariff.save(raw=raw)  # Raw = loaddata is loading fixtures for unittest


@receiver(pre_delete, sender=Tariff)
def tariff_pre_delete(sender, instance: Tariff, *_args, **_kwargs):
    if instance.is_ours() or ocpi_platform.is_hub:
        logging.info(f"Sending DELETE for tariff {instance} to all parties")
        our_party = get_our_party(OcpiRolesEnum.CPO) or get_our_party(OcpiRolesEnum.HUB)
        # Loop through all the parties which are interested in receiving Tariff updates
        for (
            base_url,
            token_base64,
            country_code,
            party_id,
            credentials,
        ) in find_endpoints_by_roles(instance.send_updates_to, OcpiModuleEnum.TARIFFS):
            url = build_item_url(
                base_url,
                instance.ocpi_master.country_code,
                instance.ocpi_master.party_id,
                instance.uid,
            )
            tasks.send_ocpi_request.delay(
                {},
                url,
                token_base64,
                country_code,
                party_id,
                our_party.country_code,
                our_party.party_id,
                method="delete",
                credentials_id=credentials.id,
                title="Tariff",
            )


# SolidTariff is an immutable model
class SolidTariff(models.Model):
    objects = PartnerManager()

    external_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True, verbose_name=_("UID")
    )
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        verbose_name=_("Currency"),
        default="EUR",
    )
    price_per_kwh = models.DecimalField(
        max_digits=12, decimal_places=6, blank=True, null=True
    )
    price_per_min = models.DecimalField(
        max_digits=15, decimal_places=10, blank=True, null=True
    )
    price_per_hr = models.DecimalField(
        max_digits=12, decimal_places=6, blank=True, null=True
    )
    price_flat = models.DecimalField(
        max_digits=12, decimal_places=6, blank=True, null=True
    )
    parking_price_per_min = models.DecimalField(
        max_digits=15, decimal_places=10, blank=True, null=True
    )
    parking_price_per_hr = models.DecimalField(
        max_digits=12, decimal_places=6, blank=True, null=True
    )
    parking_grace_period = models.IntegerField(
        blank=True, null=True, validators=[MinValueValidator(0)]
    )
    vat_percentage = models.FloatField(blank=True, null=True)
    msp = models.ForeignKey(
        CredentialsRole,
        on_delete=models.CASCADE,
        related_name="msp_credentialsrole",
        verbose_name=_("MSP details"),
        null=True,
        blank=True,
    )
    operator = models.ForeignKey(
        CredentialsRole,
        on_delete=models.CASCADE,
        related_name="operator_credentialsrole",
        verbose_name=_("CPO details"),
    )

    ocpi_tariff = models.ForeignKey(
        Tariff,
        on_delete=models.PROTECT,
        related_name="solid_tariff",
        verbose_name=_("Tariff"),
        null=True,
    )

    last_updated = models.DateTimeField(
        verbose_name=_("Last updated timestamp"), null=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Created timestamp")
    )

    def get_type(self, tariff_type: str) -> Optional[object]:
        match tariff_type:
            case "ENERGY":
                return self.price_per_kwh
            case "TIME_MIN":
                return self.price_per_min
            case "TIME_HR":
                return self.price_per_hr
            case "FLAT":
                return self.price_flat
            case "PARKING_TIME_MIN":
                return self.parking_price_per_min
            case "PARKING_TIME_HR":
                return self.parking_price_per_hr
            case _:
                return None
