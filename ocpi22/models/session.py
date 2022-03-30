from django.conf import settings
from django.db import models
from django.utils import timezone
from icecream import ic
from rest_framework.reverse import reverse

from ocpi22.choices import OcpiModuleEnum
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.tariff import Tariff, PriceComponent, TariffElement
from ocpi22.models.token import Token
from ocpi22.util import ModelUtilMixin, hours_minutes, format_cost, CURRENCY_CHOICES, apply_min_and_max, apply_step_size
from ocpi22.ocpi_util import OcpiModule, Ocpi


class Session(models.Model, ModelUtilMixin, OcpiModule):
    """
    The Session object describes one charging session. That doesn’t mean it is required that energy
    has been transferred between EV and the Charge Point. It is possible that the EV never took energy
    from the Charge Point because it was instructed not to take energy by the driver.
    But as the EV was connected to the Charge Point, some form of start tariff,
    park tariff or reservation cost might be relevant.
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id', 'country_code'],
                                    name='session_party_id_uid_country_code'),
            # models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    ocpi_module_name = OcpiModuleEnum.SESSIONS
    ocpi_serializer_class = 'ocpi22.api.SessionSaveSerializer'
    ocpi_object_owner = 'CPO'
    send_updates_to = OcpiModule.INTERESTED_PARTIES
    # send_updates_to = ('EMSP', 'HUB')

    # ISO-3166 alpha-2 country code of the CPO that owns this Session
    country_code = models.CharField(max_length=2)

    # CPO ID of the CPO that 'owns' this Session (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3)

    # The unique id that identifies the charging session in the CPO platform.
    uid = models.CharField(max_length=36)

    # The timestamp when the session became ACTIVE in the Charge Point.
    # When the session is still PENDING, this field SHALL be set to the time the Session was
    # created at the Charge Point.
    # Todo: When a Session goes from PENDING to ACTIVE, this field SHALL be update to the moment the Session went to ACTIVE in the Charge Point.
    start_date_time = models.DateTimeField()

    # The timestamp when the session was completed/finished, charging might have finished before the session ends,
    # for example: EV is full, but parking cost also has to be paid.
    end_date_time = models.DateTimeField(blank=True, null=True)

    # How many kWh are in the charge point meter at the start of the session
    start_kwh = models.FloatField(default=0.0)

    # How many kWh were charged.
    stop_kwh = models.FloatField()

    @property
    def kwh(self):
        return self.stop_kwh - self.start_kwh

    # Token used to start this charging session, including all the relevant information to identify the unique token.
    # Unique ID by which this Token can be identified.
    # This is the field used by the CPO’s system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a type=APP_USER Token, it will be a unique, by the eMSP, generated ID.
    cdr_token_uid = models.CharField(max_length=36)

    # Type of the token
    cdr_token_type = models.CharField(max_length=11, choices=Token.TYPE_CHOICES)

    # Uniquely identifies the EV driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    cdr_token_contract_id = models.CharField(max_length=36)

    AUTH_REQUEST = 'AUTH_REQUEST'
    COMMAND = 'COMMAND'
    WHITELIST = 'WHITELIST'

    AUTH_METHOD_CHOICES = (
        # Authentication request has been sent to the eMSP.
        (AUTH_REQUEST, 'Authentication request to eMSP'),

        # Command like StartSession or ReserveNow used to start the Session,
        # the Token provided in the Command was used as authorization.
        (COMMAND, 'Command from eMSP'),

        # Whitelist used for authentication, no request to the eMSP has been performed.
        (WHITELIST, 'Token on whitelist'),
    )

    # Method used for authentication.
    auth_method = models.CharField(max_length=12, choices=AUTH_METHOD_CHOICES)

    # Reference to the authorization given by the eMSP. Todo: When the eMSP provided an authorization_reference in either:
    # Todo: real-time authorization or StartSession, this field SHALL contain the same value.
    # When different authorization_reference values have been given by the eMSP that are relevant to this Session,
    # the last given value SHALL be used here.
    authorization_reference = models.CharField(max_length=36, blank=True, default='')

    # Location.id of the Location object of this CPO, on which the charging session is/was happening.
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='sessions')

    # EVSE.uid of the EVSE of this Location on which the charging session is/was happening.
    evse = models.ForeignKey(Evse, on_delete=models.PROTECT, related_name='sessions')

    # Connector.id of the Connector of this Location the charging session is/was happening.
    connector = models.ForeignKey(Connector, on_delete=models.PROTECT, related_name='sessions', blank=True, null=True)

    # Optional identification of the kWh meter.
    meter_id = models.CharField(max_length=255, blank=True, null=True)

    # ISO-4217 code of the currency of this tariff
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)

    # The total cost of the session in the specified currency. This is the price that the eMSP will
    # have to pay to the CPO. A total_cost of 0.00 means free of charge. When omitted, i.e. no price
    # information is given in the Session object, it does not imply the session is/was free of charge.
    total_cost_excl_vat = models.FloatField(blank=True, null=True)
    total_cost_incl_vat = models.FloatField(blank=True, null=True)

    ACTIVE='ACTIVE'
    COMPLETED='COMPLETED'
    INVALID='INVALID'
    PENDING='PENDING'
    RESERVATION='RESERVATION'

    # The status of this session
    STATUS_CHOICES = (
        # The session has been accepted and is active. All pre-conditions were met: Communication between EV and EVSE
        # (for example: cable plugged in correctly), EV or driver is authorized. EV is being charged,
        # or can be charged. Energy is, or is not, being transfered.
        ('ACTIVE', 'Active'),

        # The session has been finished successfully.
        # Todo: No more modifications will be made to the Session object using this state.
        ('COMPLETED', 'Completed'),

        # The Session object using this state is declared invalid and will not be billed.
        ('INVALID', 'Invalid'),

        # The session is pending, it has not yet started. Not all pre-conditions are met.
        # This is the initial state. The session might never become an active session.
        ('PENDING', 'Pending'),

        # The session is started due to a reservation, charging has not yet started.
        # The session might never become an active session.
        ('RESERVATION', 'Reservation'),
    )
    status = models.CharField(max_length=11, choices=STATUS_CHOICES, default='PENDING')

    # Credentials is not a good pointer to billing party, if start_session came through a hub
    # The party who will be billed for this Session
    credentials = models.ForeignKey('Credentials', on_delete=models.PROTECT, null=True, blank=True)
    billed_to = models.CharField(max_length=6, null=True, blank=True)

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Needed for running self.clean() when doing a save() or create()
        self.full_clean()
        return super().save(*args, **kwargs)

    def calculate_price(self, connector=None, tariffs=None) -> bool:
        """
        @param connector: For testing purposes
        @param tariffs: For testing purposes
        @return: If price is calculated, store price in self.total_cost_* and return True
        """
        connector = connector or self.connector
        if not connector and not tariffs:
            return False
        kwh: float = float(self.kwh)

        # Calculate the session duration using either a stored end time or the current time
        hours = ((self.end_date_time or timezone.now()) - self.start_date_time).seconds / 3600
        result_incl_vat: float = 0.0
        result_excl_vat: float = 0.0
        tariff: Tariff
        tariffs = tariffs or connector.get_tariffs()

        if not tariffs:
            # Cannot calculate price
            return False
        tariff: Tariff
        for tariff in tariffs:
            e: TariffElement
            # noinspection PyUnresolvedReferences
            for e in tariff.tariff_elements.all():
                pc: PriceComponent
                # noinspection PyUnresolvedReferences
                for pc in e.price_components.all():
                    excl_vat = dict(
                        ENERGY=lambda x: apply_step_size(kwh, pc.step_size, divisor=1000) * x,
                        TIME=lambda x: apply_step_size(hours, pc.step_size, divisor=3600) * x,
                        FLAT=lambda x: x
                    ).get(pc.type, lambda x: 0.0)(pc.price)
                    incl_vat = excl_vat * (1.0 + pc.vat / 100) \
                        if pc.vat else excl_vat
                    # ic(pc, excl_vat)
                    result_incl_vat += incl_vat
                    result_excl_vat += excl_vat
            result_incl_vat = apply_min_and_max(result_incl_vat, tariff.min_price_incl_vat, tariff.max_price_incl_vat)
            result_excl_vat = apply_min_and_max(result_excl_vat, tariff.min_price_excl_vat, tariff.max_price_excl_vat)

        self.total_cost_incl_vat = round(result_incl_vat + 0.001, 2)  # Try round(5.625, 2) without the + 0.001
        self.total_cost_excl_vat = round(result_excl_vat + 0.001, 2)
        # If we could figure out a price, it's a success, even if the price is 0.0
        return True

    def __str__(self):
        start_time = self.start_date_time.strftime(settings.DATETIME_FORMAT)
        return f'{self.cdr_token_uid} - {start_time} - {self.kwh}kWh - ' \
               f'EVSE {self.evse.evse_id}'
               # f'{self.connector.get_standard_display() if self.connector else "no connector"}'

    def get_absolute_url(self):
        return reverse('session-by-id', args=[self.country_code, self.party_id, self.uid])

    def total_time(self):
        if self.status == 'INVALID':
            return '-'
        end = self.end_date_time if self.end_date_time else timezone.now()
        return hours_minutes((end - self.start_date_time).seconds/3600)

    def cost(self) -> str:
        return format_cost(self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency)

    def is_final(self) -> bool:
        return self.status in (self.INVALID, self.COMPLETED)
