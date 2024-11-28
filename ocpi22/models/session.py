import os
from datetime import timedelta

import pytz
from django.contrib import admin
from django.db.models import QuerySet, Sum
from django.utils.datetime_safe import datetime
from humanize import naturaltime
from rest_framework.fields import DateTimeField

import ocpi22.logging as logging
from decimal import Decimal
from typing import Union, Optional

from django.conf import settings
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

import util

from ocpi22.choices import (
    OcpiModuleEnum,
    CDR_DIMENSION_CHOICES,
    CdrDimensionEnum,
    TOKEN_TYPE_CHOICES,
)
from ocpi22.models import enum
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.tariff import Tariff, PriceComponent, TariffElement
from ocpi22.util import (
    ModelUtilMixin,
    hours_minutes,
    format_cost,
    CURRENCY_CHOICES,
    apply_min_and_max,
    apply_step_size,
    str_to_deterministic_int,
    build_absolute_uri,
)
from ocpi22.serializers.util import SerializerCleanedUp, UTCDateTimeField
from ocpi22.ocpi.util import OcpiModule
from ocpiconnector.manager import PartnerManager


class Session(models.Model, ModelUtilMixin, OcpiModule):
    """
    The Session object describes one charging session. That doesn’t mean it is required that energy
    has been transferred between EV and the Charge Point. It is possible that the EV never took energy
    from the Charge Point because it was instructed not to take energy by the driver.
    But as the EV was connected to the Charge Point, some form of start tariff,
    park tariff or reservation cost might be relevant.
    """

    class Meta:
        verbose_name = _("session")
        verbose_name_plural = _("sessions")
        indexes = [
            models.Index(fields=["created", "status", "cdr_token_uid"]),
        ]

    ocpi_module_name = OcpiModuleEnum.SESSIONS
    ocpi_serializer_class = "ocpi22.ocpi.serializers.SessionSerializer"
    ocpi_object_owner = "CPO"
    send_updates_to = OcpiModule.INTERESTED_PARTIES
    # Non-OCPI functionality for added value services
    subscribers = os.environ.get("SESSION_SUBSCRIBERS", "").upper().split(",")

    objects = PartnerManager()

    # The party responsible for the master data for this object
    # The country_code and party_id can be found through the CredentialsRole
    ocpi_master = models.ForeignKey(
        "ocpi22.CredentialsRole", related_name="sessions", on_delete=models.PROTECT
    )

    # The unique id that identifies the charging session in the CPO platform.
    uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True, verbose_name=_("UID")
    )

    # The optional ID of the reservation, if this session is based on one
    reservation_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        blank=True,
        null=True,
        verbose_name=_("Reservation ID"),
    )
    # Todo: Add expiry_date for reservation

    @cached_property
    def ocpp_reservation_id(self) -> Optional[int]:
        id = f"{self.ocpi_master.country_code}{self.ocpi_master.party_id}{self.reservation_id}"
        return str_to_deterministic_int(id, limit=10)

    # The timestamp when the session became ACTIVE in the Charge Point.
    # When the session is still PENDING, this field SHALL be set to the time the Session was
    # created at the Charge Point.
    # Todo: When a Session goes from PENDING to ACTIVE, this field SHALL be update to the moment the Session went to ACTIVE in the Charge Point.
    start_date_time = models.DateTimeField()
    reservation_start_date_time = models.DateTimeField(blank=True, null=True)

    # The timestamp when the session was completed/finished, charging might have finished before the session ends,
    # for example: EV is full, but parking cost also has to be paid.
    end_date_time = models.DateTimeField(blank=True, null=True)

    @property
    def total_time_float(self):
        now = datetime.now(pytz.utc)
        return (
            (self.end_date_time or now) - self.start_date_time
        ).total_seconds() / 3600

    # How many kWh are in the charge point meter at the start of the session
    start_kwh = models.FloatField(default=0.0)

    # How many kWh were charged.
    stop_kwh = models.FloatField(default=0.0)

    @property
    def kwh(self):
        kwh_charged = max(Decimal(self.stop_kwh) - Decimal(self.start_kwh), Decimal(0))
        return round(kwh_charged, 3)

    @kwh.setter
    def kwh(self, value: Union[float, Decimal]) -> None:
        self.stop_kwh = Decimal(self.start_kwh) + Decimal(value)

    def update_charging_periods(
        self, kwh, soc=None, power=None, timestamp=None
    ) -> None:
        active_charging_period = self.get_active_charging_period(
            kwh, soc, power, timestamp
        )
        earlier_charging_periods: QuerySet = self.chargingperiods.order_by(
            "start_date_time"
        ).filter(start_date_time__lt=active_charging_period.start_date_time)
        first_charging_period: ChargingPeriod = earlier_charging_periods.first()
        start_date_time = (
            first_charging_period.start_date_time
            if first_charging_period
            else active_charging_period.start_date_time
        )

        assert timestamp.utcoffset() == timedelta(
            0
        ), f"Timestamp {timestamp} should be UTC"
        assert start_date_time.utcoffset() == timedelta(
            0
        ), f"Start date time {start_date_time} should be UTC"

        def _sum(dimension_type: CdrDimensionEnum) -> float:
            aggregation = CdrDimension.objects.filter(
                chargingperiod__in=earlier_charging_periods, type=dimension_type.value
            ).aggregate(Sum("volume"))
            return aggregation.get("volume__sum") or 0.0

        kwh_so_far = _sum(CdrDimensionEnum.ENERGY)
        hours_so_far = _sum(CdrDimensionEnum.TIME)
        hours = (
            (timestamp or datetime.now(pytz.utc)) - start_date_time
        ).total_seconds() / 3600
        active_charging_period.set_dimension(
            Decimal(kwh) - Decimal(kwh_so_far),
            soc,
            power,
            Decimal(hours) - Decimal(hours_so_far),
        )

    # Token used to start this charging session, including all the relevant information to identify the unique token.
    # Unique ID by which this Token can be identified.
    # This is the field used by the CPO’s system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a type=APP_USER Token, it will be a unique, by the eMSP, generated ID.
    cdr_token_uid = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, verbose_name=_("Token UID")
    )

    @property
    def token_id(self):
        # For SessionAdmin
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
        verbose_name="Authentication method",
    )

    # Reference to the authorization given by the eMSP. Todo: When the eMSP provided an authorization_reference in either:
    # Todo: real-time authorization or StartSession, this field SHALL contain the same value.
    # When different authorization_reference values have been given by the eMSP that are relevant to this Session,
    # the last given value SHALL be used here.
    authorization_reference = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH,
        blank=True,
        default="",
        verbose_name="Authorization reference",
    )

    # Location.id of the Location object of this CPO, on which the charging session is/was happening.
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="sessions",
        verbose_name=_("Location"),
    )

    # EVSE.uid of the EVSE of this Location on which the charging session is/was happening.
    evse = models.ForeignKey(
        Evse, on_delete=models.PROTECT, related_name="sessions", verbose_name=_("EVSE")
    )

    # Connector.id of the Connector of this Location the charging session is/was happening.
    connector = models.ForeignKey(
        Connector,
        on_delete=models.PROTECT,
        related_name="sessions",
        blank=True,
        null=True,
        verbose_name=_("Connector"),
    )

    # Optional identification of the kWh meter.
    meter_id = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Meter ID")
    )

    # ISO-4217 code of the currency of this tariff
    currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, verbose_name=_("Currency")
    )

    # The total cost of the session in the specified currency. This is the price that the eMSP will
    # have to pay to the CPO. A total_cost of 0.00 means free of charge. When omitted, i.e. no price
    # information is given in the Session object, it does not imply the session is/was free of charge.
    total_cost_excl_vat = models.FloatField(
        blank=True, null=True, verbose_name=_("Total cost excl. VAT")
    )
    total_cost_incl_vat = models.FloatField(
        blank=True, null=True, verbose_name=_("Total cost incl. VAT")
    )

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    INVALID = "INVALID"
    PENDING = "PENDING"
    RESERVATION = "RESERVATION"

    # The status of this session
    STATUS_CHOICES = (
        # The session has been accepted and is active. All pre-conditions were met: Communication between EV and EVSE
        # (for example: cable plugged in correctly), EV or driver is authorized. EV is being charged,
        # or can be charged. Energy is, or is not, being transfered.
        ("ACTIVE", _("Active")),
        # The session has been finished successfully.
        # Todo: No more modifications will be made to the Session object using this state.
        ("COMPLETED", _("Completed")),
        # The Session object using this state is declared invalid and will not be billed.
        ("INVALID", _("Failed")),
        # The session is pending, it has not yet started. Not all pre-conditions are met.
        # This is the initial state. The session might never become an active session.
        ("PENDING", _("Pending")),
        # The session is started due to a reservation, charging has not yet started.
        # The session might never become an active session.
        ("RESERVATION", _("Reservation")),
    )
    status = models.CharField(
        max_length=11,
        choices=STATUS_CHOICES,
        default="PENDING",
        verbose_name=_("Status"),
    )

    @admin.display(boolean=True)
    def success(self) -> bool:
        return self.status not in self.INVALID

    def __hash__(self):
        return util.member_hash(self)

    # The MSP or HUB which sent us the messages resulting in this Session
    credentials = models.ForeignKey(
        "ocpi22.Credentials",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("Credentials"),
    )

    # The party who will be billed for this Session
    billed_to = models.ForeignKey(
        "ocpi22.CredentialsRole",
        on_delete=models.PROTECT,
        related_name="billed_to_sessions",
        null=True,
        blank=True,
        verbose_name=_("Billed to"),
    )

    # The payment for this session (only on MSP platform)
    payment = models.ForeignKey(
        "payment.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("Payment"),
    )

    # Store the (error) message from CPO
    message = models.JSONField(null=True, blank=True, verbose_name=_("Message"))

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last updated")
    )

    @property
    def last_updated_str(self):
        return self.last_updated.strftime(settings.OCPI_DATE_FORMAT)

    @property
    def name(self):
        return f"{self.location.name} - {self.kwh:.1f} kWh"

    def get_admin_url(self):
        return build_absolute_uri(
            util.reverse("admin:ocpi22_session_change", args=(self.pk,))
        )

    @property
    def status_display(self):
        return "" if self.status != self.INVALID else "warning"

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_("Updated"))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_("Created"))

    def save(self, *args, **kwargs):
        # Needed for running self.clean() when doing a save() or create()
        self.stop_kwh = Decimal(round(self.stop_kwh, 3))
        self.start_kwh = Decimal(round(self.start_kwh, 3))
        # self.full_clean()
        return super().save(*args, **kwargs)

    # def set_status(self, status: str):
    #     if self.status != Session.ACTIVE:
    #         self.status = Session.ACTIVE
    #         self.save(update_fields=['status'])

    def calculate_price(self, connector=None, tariffs: Tariff = None) -> bool:
        """
        @param connector: For testing purposes
        @param tariffs: For testing purposes
        @return: If price is calculated, store price in self.total_cost_* and return True
        """

        def _calculate_price(
            kwh: float, hours: float, start_date_time: DateTimeField, flat_fee: bool
        ) -> (float, float):
            te: TariffElement = applying_tariff_element(self, start_date_time)
            if te:
                pc: PriceComponent
                total_excl_vat: float = 0.0
                total_incl_vat: float = 0.0
                for pc in te.price_components.all():
                    excl_vat = dict(
                        # Todo: Must calculate in Wh, not just when kWh is incremented
                        ENERGY=lambda x: apply_step_size(
                            kwh, pc.step_size, divisor=1000
                        )
                        * x,
                        TIME=lambda x: apply_step_size(
                            hours, pc.step_size, divisor=3600
                        )
                        * x,
                        FLAT=lambda x: x if flat_fee else 0.0,
                    ).get(pc.type, lambda x: 0.0)(pc.price)
                    incl_vat = excl_vat * (1.0 + pc.vat / 100) if pc.vat else excl_vat
                    total_incl_vat += incl_vat
                    total_excl_vat += excl_vat
                return max(total_incl_vat, 0.0), max(total_excl_vat, 0.0)
            return 0.0, 0.0

        connector: Connector = connector or self.connector
        if connector:
            tariffs = tariffs or connector.get_tariffs()
        if not connector or not tariffs:
            msg = f'Unable to calculate price for EVSE {connector.evse if connector else "N/A"} connector {connector}.'
            logging.error(msg)
            # Todo: Prevent START_SESSION on a Connector where the price cannot be calculated
            # Todo: Even better, mark the EVSE inoperative, or prevent making it available
            return False
        # Calculate the session duration using either a stored end time or the current time
        result_incl_vat: float = 0.0
        result_excl_vat: float = 0.0

        from ocpi22.cpo.api import applying_tariff_element

        if not self.chargingperiods.count():
            session_hours = self.total_time_float
            session_kwh: float = float(self.kwh)
            assert session_kwh >= 0.0, f"Invalid session kwh {session_kwh}"
            cp_incl_vat, cp_excl_vat = _calculate_price(
                session_kwh, session_hours, self.start_date_time, flat_fee=True
            )
            result_incl_vat += cp_incl_vat
            result_excl_vat += cp_excl_vat
        else:
            cp: ChargingPeriod
            apply_flat_fee = True  # Let's apply the flat fee once
            for cp in self.chargingperiods.all():
                cp_kwh = cp.get_dimension_sum(CdrDimensionEnum.ENERGY)
                cp_hours = cp.get_dimension_sum(CdrDimensionEnum.TIME)

                cp_incl_vat, cp_excl_vat = _calculate_price(
                    cp_kwh, cp_hours, cp.start_date_time, flat_fee=apply_flat_fee
                )
                apply_flat_fee = False  # Flat fee was applied once above, and not during the next for loop steps
                result_incl_vat += cp_incl_vat
                result_excl_vat += cp_excl_vat

        # Apply the minimum and maximum price specified by the Tariff of the first ChargingPeriod
        tariff = tariffs[0]  # Todo: Find min and max price from all applying Tariffs
        result_incl_vat = apply_min_and_max(
            result_incl_vat, tariff.min_price_incl_vat, tariff.max_price_incl_vat
        )
        result_excl_vat = apply_min_and_max(
            result_excl_vat, tariff.min_price_excl_vat, tariff.max_price_excl_vat
        )

        self.total_cost_incl_vat = round(
            result_incl_vat + 0.001, 2
        )  # Try round(5.625, 2) without the + 0.001
        self.total_cost_excl_vat = round(result_excl_vat + 0.001, 2)
        # If we could figure out a price, it's a success, even if the price is 0.0
        return True

    def __str__(self):
        return f"{round(self.kwh, 1)} kWh, updated {naturaltime(self.updated)}"

    def get_absolute_url(self, version=None):
        return util.reverse(
            "session-by-id",
            args=[
                version or "2.2.1",
                self.ocpi_master.country_code,
                self.ocpi_master.party_id,
                self.uid,
            ],
        )

    def total_time(self):
        if self.status == self.INVALID:
            return "-"
        return hours_minutes(self.total_time_float)

    def cost(self) -> str:
        return format_cost(
            self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency
        )

    cost.admin_order_field = "total_cost_excl_vat"

    def is_final(self) -> bool:
        return self.status in (self.INVALID, self.COMPLETED)

    def get_active_charging_period(self, kwh, soc=None, power=None, timestamp=None):
        last_period: ChargingPeriod = self.chargingperiods.order_by(
            "start_date_time"
        ).last()
        period: ChargingPeriod

        if not self.connector:
            raise ValidationError(f"Session {self.uid} has no connector specified")

        from ocpi22.cpo.api import applying_tariff_element

        tariff_element = applying_tariff_element(self, timestamp)
        previous_tariff_element = (
            applying_tariff_element(self, last_period.start_date_time)
            if last_period
            else None
        )
        valid_tariff = tariff_element.tariff if tariff_element else None

        if not tariff_element:
            logging.error(
                f"No TariffElement applies for EVSE {self.evse} connector {self.connector} at {timestamp}."
            )

        if tariff_element == previous_tariff_element:
            # print(f'Tariff {valid_tariff} (still) applies')
            period = last_period
        else:
            period = ChargingPeriod.objects.create(
                start_date_time=timestamp,
                session=self,
                tariff=valid_tariff,
            )
            if last_period:
                last_period_hours = (
                    (timestamp or datetime.now(pytz.utc)) - last_period.start_date_time
                ).total_seconds() / 3600
                last_period.set_dimension(hours=last_period_hours)
        return period

    def send_updates(self, data=None, method="put", path_components=None) -> None:
        if self.status == Session.PENDING:
            return  # Don't send updates for pending sessions per OCPI 2.2.1 specifications
        if isinstance(data, list):
            # We have a list of stuff, is it by any chance ChargingPeriods?
            if isinstance(data[0], ChargingPeriod):
                chargingperiod_data = ChargingPeriodSerializer(
                    instance=data, many=True
                ).data
                total_cost_data = TotalCostSerializer(self).data
                data = dict(
                    kwh=self.kwh,
                    last_updated=self.last_updated_str,
                    total_cost=total_cost_data,
                    charging_periods=chargingperiod_data,
                )
                method = "patch"
        assert data is None or isinstance(
            data, dict
        ), f"Expected dict, got {type(data)}"
        super().send_update_to_interested_parties(
            data=data,
            method=method,
            path_components=path_components
            or [self.ocpi_master.country_code, self.ocpi_master.party_id, self.uid],
        )


class ChargingPeriod(models.Model, ModelUtilMixin):
    """
    A Charging Period consists of a start timestamp and a list of possible values that influence this period,
    for example: amount of energy charged this period, maximum current during this period etc.
    """

    class Meta:
        ordering = ("start_date_time",)

    objects = PartnerManager()

    # Start timestamp of the charging period. A period ends when the next period starts.
    # The last period ends when the session ends.
    start_date_time = models.DateTimeField()

    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="chargingperiods"
    )

    tariff = models.ForeignKey(
        Tariff,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="chargingperiods",
    )

    def __str__(self):
        values = ", ".join(
            [
                f"{type}: {volume}"
                for type, volume in self.dimensions.all().values_list("type", "volume")
            ]
        )
        return f"{self.start_date_time} - {values}"

    def set_dimension(self, kwh=None, soc=None, power=None, hours=None):
        def _set_dimension(dimension_type, volume):
            if not volume:
                return
            dimension: CdrDimension = self.dimensions.filter(type=dimension_type).last()
            if not dimension:
                CdrDimension.objects.create(
                    type=dimension_type, volume=volume, chargingperiod=self
                )
            else:
                dimension.volume = volume
                dimension.save(update_fields=["volume"])

        dimensions = (
            (CdrDimensionEnum.ENERGY.value, kwh),
            (CdrDimensionEnum.STATE_OF_CHARGE.value, soc),
            (CdrDimensionEnum.POWER.value, power),
            (CdrDimensionEnum.TIME.value, hours),
        )
        for args in dimensions:
            _set_dimension(*args)

    def get_dimension_sum(self, dimension_type: CdrDimensionEnum) -> float:
        q: QuerySet
        q = self.dimensions.filter(type=dimension_type.value)
        aggregation = q.aggregate(Sum("volume"))
        return float(aggregation.get("volume__sum") or 0.0)


class CdrDimension(models.Model):
    # Type of CDR dimension.
    type = models.CharField(max_length=16, choices=CDR_DIMENSION_CHOICES)

    # Volume of the dimension consumed, measured according to the dimension type.
    volume = models.DecimalField(max_digits=12, decimal_places=4)

    chargingperiod = models.ForeignKey(
        ChargingPeriod, on_delete=models.CASCADE, related_name="dimensions"
    )

    def __str__(self):
        return f"{self.type}: {self.volume}"


#
# These serializers are here to avoid import loops and repetitive imports
# - They are heavily used
#


class CdrDimensionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CdrDimension
        fields = ("type", "volume")


class TariffIdSerializer(serializers.Serializer):
    def to_representation(self, instance):
        return instance.uid

    def to_internal_value(self, data):
        return Tariff.objects.filter(uid=data).first()


class ChargingPeriodSerializer(serializers.Serializer):
    start_date_time = UTCDateTimeField(required=False)
    tariff = TariffIdSerializer()
    dimensions = CdrDimensionSerializer(many=True)


class TotalCostSerializer(SerializerCleanedUp):
    excl_vat = serializers.FloatField(source="total_cost_excl_vat", required=False)
    incl_vat = serializers.FloatField(source="total_cost_incl_vat", required=False)
