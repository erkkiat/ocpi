import uuid
from collections import Counter

from django.conf import settings
from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.urls import NoReverseMatch
from django.utils.html import format_html
from icecream import ic
from rest_framework.reverse import reverse

from ocpi22.choices import OcpiModuleEnum
from ocpi22.logging import log_error
from ocpi22.models.models import Facility, Capability
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.util import ModelUtilMixin, uid_validator, calculate_partition
from ocpi22.ocpi.util import OcpiModule, Ocpi
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id


class Location(models.Model, ModelUtilMixin, OcpiModule):
    """
    A physical location with one or more EVSEs
    """

    ocpi_serializer_class = 'ocpi22.locations.serializers.LocationSerializer'
    ocpi_module_name = OcpiModuleEnum.LOCATIONS
    ocpi_object_owner = 'CPO'
    send_updates_to = ('EMSP', 'NAP', 'NSP', 'HUB')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'party_id'], name='party_uid'),
            models.UniqueConstraint(fields=['uid', 'suboperator', 'operator'], name='operator_suboperator_uid'),
        ]

    upper_case_fields = ['postal_code', 'country', 'country_code', 'party_id', 'uid']

    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2, default=get_our_country_code(ocpi_object_owner))

    # CPO ID of the CPO that 'owns' this Location (following the ISO-15118 standard).
    party_id = models.CharField(max_length=3, default=get_our_party_id(ocpi_object_owner))

    # Uniquely identifies the location within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True)

    # Defines if a Location may be published on an website or app etc.
    # When this is set to false, only tokens identified in the field:
    # publish_allowed_to are allowed to be shown this Location.
    # When the same location has EVSEs that may be published and may not be published,
    # two 'Locations' should be created.
    publish = models.BooleanField(default=True)

    # Defines the set of values that identify a token to which a Location might be published.
    # At least one of the following fields SHALL be set: uid, visual_number, or group_id.
    #
    # When uid is set, type SHALL also be set.
    publish_allowed_to = models.ManyToManyField(Token, related_name='locations', blank=True)

    # Display name of the location
    name = models.CharField(max_length=255, blank=True)

    # Street/block name and house number if available.
    address = models.CharField(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)

    # City or town
    city = models.CharField(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH)

    # Postal code of the location, may only be omitted when the location has no postal code:
    # in some countries charging locations at highways don’t have postal codes.
    postal_code = models.CharField(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH, blank=True)

    # State or province of the location, only to be used when relevant
    state = models.CharField(max_length=20, blank=True)

    # ISO 3166-1 alpha-3 code for the country of this location
    country = models.CharField(max_length=3)

    # This class defines the geo location of the Charge Point. The geodetic system to be used is WGS 84.
    latitude = models.FloatField()
    longitude = models.FloatField()

    def get_coordinates(self):
        """Formatting for OCPI (2.2)"""
        return dict(latitude=self.latitude, longitude=self.longitude)

    def set_coordinates(self, value):
        raise NotImplementedError()

    coordinates = property(get_coordinates, set_coordinates)

    # An index for fast lookup, first 4 digits from lat
    lat_partition = models.SmallIntegerField(db_index=True, null=True, blank=True)
    # An index for fast lookup, first 4 digits from long
    long_partition = models.SmallIntegerField(db_index=True, null=True, blank=True)

    # Geographical location of related points relevant to the user
    # related_locations

    # The general type of parking at the charge point location
    PARKING_CHOICES = (
        ('ALONG_MOTORWAY', 'Along a motorway'),
        ('PARKING_GARAGE', 'Parking garage'),
        ('PARKING_LOT', 'Parking lot'),
        ('ON_DRIVEWAY', 'Driveway'),
        ('ON_STREET', 'Street'),
        ('UNDERGROUND_GARAGE', 'Underground garage'),
    )
    parking_type = models.CharField(max_length=18, null=True, blank=True, choices=PARKING_CHOICES)

    # List of EVSEs that belong to this Location
    # evses (comes automatically from Evse class)

    # Human-readable directions on how to reach the location
    # directions

    operator = models.ForeignKey(BusinessDetails, related_name='operator_locations',
                                 null=True, blank=True, on_delete=models.PROTECT)
    suboperator = models.ForeignKey(BusinessDetails, related_name='suboperator_locations',
                                    null=True, blank=True, on_delete=models.PROTECT)
    owner = models.ForeignKey(BusinessDetails, related_name='owner_locations',
                              null=True, blank=True, on_delete=models.PROTECT)

    # Optional list of facilities this charging location directly belongs to
    facilities = models.ManyToManyField(Facility, related_name='facility_locations', blank=True)

    # Todo: get time zone based on coordinates
    # One of IANA tzdata’s TZ-values representing the time zone of the location.
    # Examples: "Europe/Oslo", "Europe/Zurich". (http://www.iana.org/time-zones)
    time_zone = models.CharField(max_length=settings.OCPI_22_MAX_TIME_ZONE_LENGTH)

    # The times when the EVSEs at the location can be accessed for charging
    # opening_times

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name}, {self.address}, {self.city}' or f'[No name, UID: {self.pk}]'

    def save(self, *args, **kwargs):
        self.change_fields_to_upper_case()
        return super(self.__class__, self).save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('location-by-id', args=[self.country_code, self.party_id, self.uid])

    def get_quick_url(self):
        return reverse('quick-location-by-id', args=[self.uid])

    def street_address(self):
        return f'{self.address}, {self.postal_code} {self.city}, {self.state} {self.country}'

    def evse_count(self):
        # noinspection PyUnresolvedReferences
        return self.evses.count()

    def evse_list(self):
        # noinspection PyUnresolvedReferences
        return format_html(
            '<hr style="margin: 4px">'.join(
                [
                    f'<a href="{reverse("admin:ocpi22_evse_change", args=[e.pk])}">{str(e)}</a>'
                    for e in self.evses.all()
                ]
            )
        )

    def available(self):
        standards_available = []
        for evse in self.evses.filter(status='AVAILABLE'):
            for connector in evse.connectors.all():
                standards_available.append(connector.standard)
        return Counter(standards_available)

    def get_prices_str(self):
        results = []
        for evse in self.evses.all():
            for connector in evse.connectors.all():
                results.append(f'{connector.get_standard_display()}: {connector.tariff()}')
        return ", ".join(set(results))


class Evse(models.Model, ModelUtilMixin):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['uid', 'location'], name='evse_party_uid'),
        ]

    # Uniquely identifies the EVSE within the CPOs platform (and suboperator platforms).
    # For example a database ID or the actual "EVSE ID". This field can never be changed, modified or renamed.
    # This is the 'technical' identification of the EVSE, not to be used as 'human readable' identification,
    # use the field evse_id for that.
    # This field is named uid instead of id, because id could be confused with evse_id which is an eMI3 defined field.
    uid = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, validators=[uid_validator], db_index=True)

    # Compliant with the following specification for EVSE ID from "eMI3 standard version V1.0"
    # (http://emi3group.com/documents-links/) "Part 2: business objects."
    # Optional because: if an evse_id is to be re-used in the real world,
    # the evse_id can be removed from an EVSE object if the status is set to REMOVED.

    evse_id = models.CharField(max_length=48, blank=True, default='')

    AVAILABLE = 'AVAILABLE'
    BLOCKED = 'BLOCKED'
    CHARGING = 'CHARGING'
    INOPERATIVE = 'INOPERATIVE'
    OUTOFORDER = 'OUTOFORDER'
    PLANNED = 'PLANNED'
    REMOVED = 'REMOVED'
    RESERVED = 'RESERVED'
    UNKNOWN = 'UNKNOWN'

    # Indicates the current status of the EVSE
    STATUS_CHOICES = (
        (AVAILABLE, 'Available'),
        (BLOCKED, 'Physically blocked'),
        (CHARGING, 'Charging'),
        (INOPERATIVE, 'Inoperative (not yet active or it is no longer available)'),
        (OUTOFORDER, 'Out of order'),
        (PLANNED, 'Planned, will be operating soon'),
        (REMOVED, 'Discontinued/removed'),
        (RESERVED, 'Reserved for a particular EV driver'),
        (UNKNOWN, 'No status information available (also used when offline)'),
    )
    status = models.CharField(max_length=11, choices=STATUS_CHOICES)

    CAPABILITY_CHOICES = (
        ('CHARGING_PROFILE_CAPABLE', 'The EVSE supports charging profiles'),
        ('CHARGING_PREFERENCES_CAPABLE', 'The EVSE supports charging preferences'),
        ('CHIP_CARD_SUPPORT', 'EVSE has a payment terminal that supports chip cards'),
        ('CONTACTLESS_CARD_SUPPORT', 'EVSE has a payment terminal that supports contactless cards'),
        ('CREDIT_CARD_PAYABLE', 'EVSE has a payment terminal that makes it possible to pay for charging using a credit card'),
        ('DEBIT_CARD_PAYABLE', 'EVSE has a payment terminal that makes it possible to pay for charging using a debit card'),
        ('PED_TERMINAL', 'EVSE has a payment terminal with a pin-code entry device'),
        ('REMOTE_START_STOP_CAPABLE', 'The EVSE can remotely be started / stopped'),
        ('RESERVABLE', 'The EVSE can be reserved'),
        ('RFID_READER', 'Charging at this EVSE can be authorized with an RFID token'),
        ('TOKEN_GROUP_CAPABLE', 'This EVSE supports token groups, two or more tokens work as one'),
        ('UNLOCK_CAPABLE', 'Connectors can be unlocked remotely'),
    )
    capabilities = models.ManyToManyField(Capability, related_name='evses')

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='evses')

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.evse_id

    def connector_list(self):
        # noinspection PyUnresolvedReferences
        return format_html(
            '<hr style="margin: 4px">'.join([f'{str(c)}<br>{c.tariff_html()}' for c in self.connectors.all()])
        )

    def get_absolute_url(self):
        try:
            return reverse('location-by-evse-id',
                           args=[self.location.country_code, self.location.party_id, self.location.uid, self.uid])
        except NoReverseMatch:
            return ''

    def get_cpo_url(self):
        try:
            return reverse('cpo-evse-by-id',
                           args=[self.uid])
        except NoReverseMatch:
            return ''

    def get_status_url(self):
        try:
            return reverse('cpo-evse-by-id',
                           args=[self.uid])
        except NoReverseMatch:
            return ''

    def send_status_updates(self) -> None:
        data = dict(
            status=self.status,
            last_updated=self.last_updated
        )
        location = self.location
        method = 'patch'
        Location._send_updates(data, method=method,
                               path_components=[location.country_code, location.party_id, location.uid, self.uid])


class Connector(models.Model, ModelUtilMixin):
    # Identifier of the Connector within the EVSE. Two Connectors may have the same id
    # as long as they do not belong to the same EVSE object.

    class Meta:
        unique_together = [['evse', 'uid']]

    uid = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True)

    evse = models.ForeignKey(Evse, on_delete=models.CASCADE, related_name='connectors')

    standard = models.CharField(max_length=21, choices=Ocpi.STANDARD_CHOICES)

    format = models.CharField(max_length=6, choices=Ocpi.FORMAT_CHOICES)

    power_type = models.CharField(max_length=10, choices=Ocpi.POWERTYPE_CHOICES)

    max_voltage = models.SmallIntegerField()
    max_amperage = models.SmallIntegerField()
    max_electric_power = models.IntegerField(null=True, blank=True)

    tariff_ids = models.ManyToManyField(Tariff, related_name='tariffs', blank=True)

    terms_and_conditions = models.URLField(blank=True, default='')

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'#{self.uid} - {self.get_standard_display()} - {self.power()}'

    def power(self):
        return f'{int((self.max_electric_power or self.max_voltage * self.max_amperage) / 1000)} kW'

    def tariff(self):
        return ','.join([t.price() for t in self.tariff_ids.all()])

    def tariff_html(self):
        return format_html('<br>'.join([t.link() for t in self.tariff_ids.all()]))

    def get_tariffs(self):
        # Fetch the Tariffs specified for this Connector or find a DefaultTariff in case no specific Tariffs
        tariffs = self.tariff_ids.all() or Tariff.get_default_tariffs(self.standard)
        if tariffs.count() > 1:
            log_error(str=f'Multiple Tariffs for Connector {str(self.evse)} {str(self)}')
        return tariffs


@receiver(pre_save, sender=Evse)
def evse_pre_save(sender, instance: Evse, *_args, **_kwargs):
    if not instance.evse_id:
        instance.evse_id = f'{instance.location.country_code}*{instance.location.party_id}*E{instance.uid}'


@receiver(pre_save, sender=Connector)
def connector_pre_save(sender, instance, *_args, **_kwargs):
    connector: Connector = instance
    if not connector.uid:
        connector.uid = uuid.uuid4().hex
    if not connector.power_type:
        connector.power_type = Ocpi.POWERTYPES[connector.standard]


@receiver(post_save, sender=Connector)
def connector_post_save(sender, instance, *_args, **kwargs):
    # ic()
    # ic(kwargs)
    connector: Connector = instance
    evse = connector.evse
    # ic('connector_post_save is updating Evse.last_updated')
    evse.last_updated = connector.last_updated
    evse.save(update_fields=['last_updated'])
    # ic('connector_post_save is updating Location.last_updated')
    location = connector.evse.location
    location.last_updated = connector.last_updated
    location.save(update_fields=['last_updated'])


@receiver(post_save, sender=Evse)
def evse_post_save(sender, instance, *_args, **kwargs):
    """
    Make sure that only Admin calls Evse.save() without the update_fields list
    """
    # ic()
    # ic(kwargs)
    update_fields = kwargs.get('update_fields', [])
    if update_fields and 'last_updated' in update_fields:
        # If only last_updated has been changed, Location.last_updated has been already updated by connector_post_save
        # ic('evse_post_save was triggered by connector_post_save, no updating for Location.last_updated')
        return
    # ic('evse_post_save is updating Location.last_updated')
    evse = instance
    evse.location.last_updated = evse.last_updated
    evse.location.save(update_fields=['last_updated'])
    # if location.is_ours():
    #     ic('*** This is our location, sending updates to all known parties')
    #     # from ocpi22.location import send_evse_updates
    #     # send_evse_updates(evse.uid)
    #     from ocpi22.location import send_location_updates
    #     send_location_updates(location)


@receiver(pre_save, sender=Location)
def location_pre_save(sender, instance, *_args, **_kwargs):
    location: Location = instance
    location.lat_partition = calculate_partition(location.latitude)
    location.long_partition = calculate_partition(location.longitude)