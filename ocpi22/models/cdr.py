import logging
import uuid

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.reverse import reverse

from ocpi22.choices import OcpiModuleEnum
from ocpi22.models.tariff import Tariff
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.msp.account import check_balance
from ocpi22.util import format_cost, hours_minutes, ModelUtilMixin, CURRENCY_CHOICES
from ocpi22.ocpi.util import OcpiModule, Ocpi
from ocpiconnector.ocpi_identities import ocpi_platform


class Cdr(models.Model, ModelUtilMixin, OcpiModule):
    """
    A Charge Detail Record is the description of a concluded charging session.
    The CDR is the only billing-relevant object. CDRs are sent from the CPO to the eMSP
    after the charging session has ended. Although there is no requirement to send CDRs in (semi-) realtime,
    it is seen as good practice to send them as soon as possible. But if there is an agreement between
    parties to send them, for example, once a month, that is also allowed by OCPI.
    """

    ocpi_module_name = OcpiModuleEnum.CDRS
    ocpi_serializer_class = 'ocpi22.ocpi.serializers.CdrSerializer'
    ocpi_object_owner = 'CPO'
    send_updates_to = OcpiModule.INTERESTED_PARTIES
    # send_updates_to = ('EMSP', 'HUB')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id'], name='cdr_party_uid'),
            # Todo: models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    # ISO-3166 alpha-2 country code of the CPO that owns this CDR
    country_code = models.CharField(max_length=2)

    # CPO ID of the CPO that 'owns' this CDR (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3)

    # Uniquely identifies the CDR within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=39, db_index=True)

    # Start timestamp of the charging session, or in-case of a reservation
    # (before the start of a session) the start of the reservation.
    start_date_time = models.DateTimeField()

    # The timestamp when the session was completed/finished, charging might have finished before
    # the session ends, for example: EV is full, but parking cost also has to be paid.
    end_date_time = models.DateTimeField()

    # Unique ID of the Session for which this CDR is sent. Is only allowed to be omitted
    # when the CPO has not implemented the Sessions module or this CDR is the result of a reservation
    # that never became a charging session, thus no OCPI Session.
    session_id = models.CharField(max_length=36, blank=True, default='')
    # Todo: Make this a Foreignkey

    # Token used to start this charging session, includes all the relevant information to identify the unique token.
    cdr_token_uid = models.CharField(max_length=36)

    # Type of the token
    cdr_token_type = models.CharField(max_length=11, choices=Token.TYPE_CHOICES)

    # Uniquely identifies the EV driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    cdr_token_contract_id = models.CharField(max_length=36)

    # Method used for authentication.
    auth_method = models.CharField(max_length=12, choices=Session.AUTH_METHOD_CHOICES)

    # Reference to the authorization given by the eMSP. When the eMSP provided an authorization_reference in either:
    # real-time authorization or StartSession, this field SHALL contain the same value.
    # When different authorization_reference values have been given by the eMSP that are relevant to this Session,
    # the last given value SHALL be used here.
    authorization_reference = models.CharField(max_length=36, blank=True, default='')

    # Location where the charging session took place, including only the relevant EVSE and Connector.
    # Uniquely identifies the location within the CPO’s platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    cdr_location_id = models.CharField(max_length=36)

    # Street/block name and house number if available.
    cdr_location_address = models.CharField(max_length=45)

    # Display name of the location.
    cdr_location_name = models.CharField(max_length=255, blank=True, null=True)

    # City or town.
    cdr_location_city = models.CharField(max_length=45)

    # Postal code of the location.
    cdr_location_postal_code = models.CharField(max_length=10)

    # ISO 3166-1 alpha-3 code for the country of this location.
    cdr_location_country = models.CharField(max_length=3)

    # Coordinates of the location.
    cdr_location_latitude = models.CharField(max_length=10)
    cdr_location_longitude = models.CharField(max_length=11)

    # Uniquely identifies the EVSE within the CPO’s platform (and suboperator platforms).
    # For example a database unique ID or the actual EVSE ID. This field can never be changed, modified or renamed.
    # This is the technical identification of the EVSE, not to be used as human readable identification,
    # use the field: evse_id for that.
    cdr_location_evse_uid = models.CharField(max_length=36)

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects.".
    cdr_location_evse_id = models.CharField(max_length=48)

    # Identifier of the connector within the EVSE.
    cdr_location_connector_id = models.CharField(max_length=36)

    # The standard of the installed connector.
    cdr_location_connector_standard = models.CharField(max_length=21, choices=Ocpi.STANDARD_CHOICES)

    # The format (socket/cable) of the installed connector.
    cdr_location_connector_format = models.CharField(max_length=6, choices=Ocpi.FORMAT_CHOICES)

    # The power type of the connector (AC/DC, phases)
    cdr_location_connector_power_type = models.CharField(max_length=10, choices=Ocpi.POWERTYPE_CHOICES)

    # Currency of the CDR in ISO 4217 Code.
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)

    # List of relevant Tariff Elements, see: Tariff. When relevant, a Free of Charge tariff
    # should also be in this list, and point to a defined Free of Charge Tariff.
    tariffs = models.ManyToManyField(Tariff, blank=True)

    # Total sum of all the costs of this transaction in the specified currency.
    total_cost_excl_vat = models.FloatField()
    total_cost_incl_vat = models.FloatField(blank=True, null=True)

    # Total energy charged, in kWh.
    total_energy = models.FloatField()

    # Total duration of the charging session (including the duration of charging and not charging), in hours.
    total_time = models.FloatField()

    # When set to true, this is a Credit CDR, and the field credit_reference_id needs to be set as well.
    # Todo: Make a "create credit CDR" management command
    credit = models.BooleanField(default=False)
    credit_reference = models.ForeignKey('Cdr', blank=True, null=True, on_delete=models.PROTECT)

    # The party who will be billed for the transaction
    billed_to = models.CharField(max_length=6, blank=True)

    # The party who will be billed for this Session
    credentials = models.ForeignKey('Credentials', on_delete=models.PROTECT, null=True, blank=True)

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.end_date_time:%d.%m.%Y} - {self.cdr_token_uid} - ' \
               f'{format_cost(self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency)} - ' \
               f'{hours_minutes(self.total_time)}'

    def get_absolute_url(self):
        return reverse('cdr-by-id', args=[self.country_code, self.party_id, self.uid])

    def total_cost(self):
        return f'{"-" if self.credit else ""}' \
               f'{format_cost(self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency)}' \
               f'{" (credited)" if self.credit else ""}'

    def total_session_time(self):
        return hours_minutes(self.total_time)

    @classmethod
    def create_based_on_session(cls, session: Session):
        # Was there already a CDR created for this Session?
        cdr = cls.objects.filter(session_id=session.uid)
        # if cdr.exists():
        #     raise ValidationError(dict(status_text=f'A CDR has already been created for session `{session.uid}`'))
        if session.total_cost_excl_vat is None:
            logging.error(f'{settings.HOSTNAME}: Session {session} has no total cost')
        if not session.end_date_time:
            session.end_date_time = timezone.now()

        # noinspection PyUnresolvedReferences
        cdr = cls.objects.create(
            uid=uuid.uuid4().hex,
            country_code=session.country_code,
            party_id=session.party_id,
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
            cdr_location_postal_code=session.location.postal_code or '-',
            cdr_location_country=session.location.country,

            # Make sure coordinates have 6 decimals
            cdr_location_latitude=f'{float(session.location.latitude):.6f}',
            cdr_location_longitude=f'{float(session.location.longitude):.6f}',

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
            total_time=round((session.end_date_time - session.start_date_time).seconds / 3600.0, 5),
            credentials=session.credentials,
            billed_to=session.billed_to,
            last_updated=timezone.now(),
        )
        tariffs = session.connector.tariff_ids.all()
        if tariffs.count():
            cdr_tariffs = Tariff.make_copies(tariffs)
        else:
            cdr_tariffs = Tariff.make_copies(Tariff.get_default_tariffs(session.connector.standard))
        cdr.tariffs.set(cdr_tariffs)

        cdr.send_updates()

        return cdr

    @classmethod
    def session_changed(cls, instance: Session) -> None:
        if instance.status == Session.COMPLETED and instance.is_ours():
            existing_cdr = Cdr.get_if_exists(session_id=instance.uid)
            # ic(existing_cdr)
            if not existing_cdr:
                _new_cdr = Cdr.create_based_on_session(instance)
                # ic(_new_cdr)

    def cost(self) -> str:
        return format_cost(self.total_cost_incl_vat, self.total_cost_excl_vat, self.currency)


@receiver(post_save, sender=Session)
def session_post_save(sender, instance: Session, *_args, **_kwargs):
    Cdr.session_changed(instance)
    if ocpi_platform.is_emsp:
        check_balance(instance)
