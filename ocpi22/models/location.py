import uuid
from collections import Counter
from django.utils.datetime_safe import datetime

import pytz
from dateutil import tz
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.urls import NoReverseMatch
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext as _

from ocpi22 import choices
import util

from ocpi22.choices import OcpiModuleEnum
from ocpi22.models.models import Facility, Capability
from ocpi22.models.business_details import BusinessDetails
from ocpi22.util import ModelUtilMixin, uid_validator, calculate_partition, build_absolute_uri
from ocpi22.ocpi.util import OcpiModule, Ocpi
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id


def validate_timezone(t: str):
    if not tz.gettz(t):
        raise ValidationError(
            _('Timezone "%(value)s" is unknown.'),
            params={'value': t},
        )


#
# For use in the future
#
# class OCPIPeriod(models.Model):
#     period_begin = models.DateTimeField()
#     period_end = models.DateTimeField()
#
#
# class OCPIDayPeriod(models.Model):
#     WEEKDAYS = [
#         (0, 'Monday'),
#         (1, 'Tuesday'),
#         (2, 'Wednesday'),
#         (3, 'Thursday'),
#         (4, 'Friday'),
#         (5, 'Saturday'),
#         (6, 'Sunday'),
#     ]
#     weekday = models.IntegerField(choices=WEEKDAYS)
#
#     time_validator = RegexValidator(regex=r'^[0-2][0-9]:[0-5][0-9]$')
#     period_begin = models.CharField(max_length=5, validators=[time_validator])
#     period_end = models.CharField(max_length=5, validators=[time_validator])
#
#
# class OCPIOpeningTimes(models.Model):
#     regular_hours = models.ManyToManyField(OCPIDayPeriod, blank=True)
#     twentyfourseven = models.BooleanField(default=False)
#     exceptional_openings = models.ManyToManyField(OCPIPeriod, related_name='exceptional_openings', blank=True)
#     exceptional_closings = models.ManyToManyField(OCPIPeriod, related_name='exceptional_closings', blank=True)


class Location(OcpiModule, models.Model, ModelUtilMixin):
    """
    A physical location with one or more EVSEs
    """

    ocpi_serializer_classes = {
        '22': 'ocpi22.locations.serializers.LocationSerializer',
        '221': 'ocpi22.locations.serializers.LocationSerializer221'
    }
    ocpi_module_name = OcpiModuleEnum.LOCATIONS
    ocpi_object_owner = 'CPO'
    send_updates_to = ('EMSP', 'NAP', 'NSP', 'HUB', 'OTHER')

    class Meta:
        verbose_name = _('location')
        verbose_name_plural = _('locations')

        constraints = [
            models.UniqueConstraint(fields=['uid', 'ocpi_master'], name='unique_uid_per_ocpi_master'),
        ]
        indexes = [
            models.Index(fields=['uid', 'ocpi_master']),
        ]

    upper_case_fields = ['postal_code', 'country', 'uid']

    # The party that owns this Location
    # The country_code and party_id can be found through the CredentialsRole
    ocpi_master = models.ForeignKey('ocpi22.CredentialsRole', related_name='locations', on_delete=models.PROTECT)

    # Uniquely identifies the location within the CPOs platform (and suboperator platforms).
    # This field can never be changed, modified or renamed.
    uid = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True, verbose_name=_('UID'))

    # Defines if a Location may be published on an website or app etc.
    # When this is set to false, only tokens identified in the field:
    # publish_allowed_to are allowed to be shown this Location.
    # When the same location has EVSEs that may be published and may not be published,
    # two 'Locations' should be created.
    publish = models.BooleanField(default=True, verbose_name=_('Publish'))

    # Defines the set of values that identify a token to which a Location might be published.
    # At least one of the following fields SHALL be set: uid, visual_number, or group_id.
    #
    # When uid is set, type SHALL also be set.
    publish_allowed_to = models.ManyToManyField("Token", related_name='locations', blank=True,
                                                verbose_name=_('Publish allowed to'))

    # Display name of the location
    name = models.CharField(max_length=255, blank=True, verbose_name=_('Name'))

    # Street/block name and house number if available.
    address = models.CharField(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH, verbose_name=_('Address'))

    # City or town
    city = models.CharField(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH, verbose_name=_('City'))

    # Postal code of the location, may only be omitted when the location has no postal code:
    # in some countries charging locations at highways don’t have postal codes.
    postal_code = models.CharField(max_length=settings.OCPI_22_MAX_ADDRESS_LENGTH, blank=True,
                                   verbose_name=_('Postal code'))

    # State or province of the location, only to be used when relevant
    state = models.CharField(max_length=20, blank=True, verbose_name=_('State'))

    # ISO 3166-1 alpha-3 code for the country of this location
    country = models.CharField(max_length=3, choices=choices.COUNTRIES_ISO_3, verbose_name=_('Country'))

    # This class defines the geo location of the Charge Point. The geodetic system to be used is WGS 84.
    latitude = models.FloatField(verbose_name=_('Latitude'))
    longitude = models.FloatField(verbose_name=_('Longitude'))

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
    parking_type = models.CharField(max_length=18, null=True, blank=True, choices=PARKING_CHOICES,
                                    verbose_name=_('Parking type'))

    # List of EVSEs that belong to this Location
    # evses (comes automatically from Evse class)

    # Human-readable directions on how to reach the location
    # directions

    operator = models.ForeignKey(BusinessDetails, related_name='operator_locations',
                                 null=True, blank=True, on_delete=models.PROTECT, verbose_name=_('Operator'))
    suboperator = models.ForeignKey(BusinessDetails, related_name='suboperator_locations',
                                    null=True, blank=True, on_delete=models.PROTECT, verbose_name=_('Suboperator'))
    owner = models.ForeignKey(BusinessDetails, related_name='owner_locations',
                              null=True, blank=True, on_delete=models.PROTECT, verbose_name=_('Owner'))

    # Optional list of facilities this charging location directly belongs to
    facilities = models.ManyToManyField(Facility, related_name='facility_locations', blank=True,
                                        verbose_name=_('Facilities'))

    # Todo: get time zone based on coordinates
    # One of IANA tzdata’s TZ-values representing the time zone of the location.
    # Examples: "Europe/Oslo", "Europe/Zurich". (http://www.iana.org/time-zones)
    time_zone = models.CharField(max_length=settings.OCPI_22_MAX_TIME_ZONE_LENGTH, validators=[validate_timezone],
                                 verbose_name=_('Time zone'), choices=choices.TIMEZONE_CHOICES)

    def get_timezone(self):
        return tz.gettz(self.time_zone)

    # The times when the EVSEs at the location can be accessed for charging
    # opening_times

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))

    def __str__(self):
        return f'{self.name}, {self.address}, {self.city}' or f'[No name, UID: {self.pk}]'

    def save(self, *args, **kwargs):
        self.change_fields_to_upper_case()
        if self.is_ours():
            self.last_updated = datetime.now(pytz.utc)
        self.lat_partition = calculate_partition(self.latitude)
        self.long_partition = calculate_partition(self.longitude)
        return super(self.__class__, self).save(*args, **kwargs)

    def get_absolute_url(self, version=None):
        return util.reverse(
            'location-by-id',
            args=[version or '2.2.1', self.ocpi_master.country_code, self.ocpi_master.party_id, self.uid]
        )

    def get_admin_url(self):
        return build_absolute_uri(util.reverse('admin:ocpi22_location_change', args=(self.pk,)))

    def get_quick_url(self):
        return util.reverse('quick-location-by-id', args=[self.uid])

    def street_address(self):
        return f'{self.address}, {self.postal_code} {self.city}, {self.state} {self.country}'

    def evse_count(self):
        return self.evses.count()

    def __hash__(self):
        return util.member_hash(self)

    def evse_list(self):
        return format_html(
            '<hr style="margin: 4px">'.join(
                [
                    f'<a href="{util.reverse("admin:ocpi22_evse_change", args=[e.pk])}">{str(e)}</a>'
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
        verbose_name = _('charge point')
        verbose_name_plural = _('charge points')
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

    evse_id = models.CharField(max_length=48, blank=True, default='', verbose_name=_('EVSE ID'))

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
        (AVAILABLE, _('Available')),
        (BLOCKED, _('Physically blocked')),
        (CHARGING, _('Charging')),
        (INOPERATIVE, _('Inoperative')),
        (OUTOFORDER, _('Out of order')),
        (PLANNED, _('Planned, will be operating soon')),
        (REMOVED, _('Discontinued/removed')),
        (RESERVED, _('Reserved for a particular EV driver')),
        (UNKNOWN, _('No status information available (also used when offline)')),
    )
    status = models.CharField(max_length=11, choices=STATUS_CHOICES, verbose_name=_('Status'), default=PLANNED)

    capabilities = models.ManyToManyField(Capability, related_name='evses', blank=True, verbose_name=_('Capabilities'))

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='evses', verbose_name=_('Location'))

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True, verbose_name=_('Last updated'))

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))

    def __str__(self):
        return self.evse_id

    def connector_list(self):
        return format_html(
            '<hr style="margin: 4px">'.join([f'{str(c)}<br>{c.tariff_html()}' for c in self.connectors.all()])
        )

    def get_absolute_url(self, version=None):
        try:
            return util.reverse('location-by-evse-id',
                           args=[version or '2.2.1',
                                 self.location.ocpi_master.country_code,
                                 self.location.ocpi_master.party_id,
                                 self.location.uid, self.uid])
        except NoReverseMatch:
            return ''

    def get_cpo_url(self):
        try:
            return util.reverse('cpo-evse-by-id',
                           args=[self.uid])
        except NoReverseMatch:
            return ''

    def get_status_url(self):
        try:
            return util.reverse('cpo-evse-by-id',
                           args=[self.uid])
        except NoReverseMatch:
            return ''

    def send_status_updates(self) -> None:
        data = dict(
            status=self.status,
            last_updated=self.last_updated
        )
        location = self.location
        location.send_all_updates(
            data=data, method='patch',
            path_components=[location.ocpi_master.country_code, location.ocpi_master.party_id, location.uid, self.uid]
        )

    def save(self, *args, **kwargs):
        if self.location.is_ours():
            self.last_updated = datetime.now(pytz.utc)
            self.location.last_updated = datetime.now(pytz.utc)
            self.location.save(update_fields=['last_updated'])
        return super().save(*args, **kwargs)

    def party_long(self) -> str:
        if hasattr(self, 'location') and hasattr(self.location, 'ocpi_master') and self.location.ocpi_master:
            return f'{self.location.ocpi_master.business_details.name}' \
                f' ({self.location.ocpi_master.country_code}*{self.location.ocpi_master.party_id})'
        return self.party()
    party_long.short_description = _('Charge Point Owner')


class Connector(models.Model, ModelUtilMixin):
    # Identifier of the Connector within the EVSE. Two Connectors may have the same id
    # as long as they do not belong to the same EVSE object.

    class Meta:
        verbose_name = _('connector')
        verbose_name_plural = _('connectors')
        unique_together = [['evse', 'uid']]

    uid = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True)

    evse = models.ForeignKey(Evse, on_delete=models.CASCADE, related_name='connectors')

    standard = models.CharField(max_length=21, choices=Ocpi.STANDARD_CHOICES, verbose_name=_('Standard'))

    format = models.CharField(max_length=6, choices=Ocpi.FORMAT_CHOICES, verbose_name=_('Format'))

    power_type = models.CharField(max_length=16, choices=Ocpi.POWERTYPE_CHOICES_221, verbose_name=_('Power type'))

    max_voltage = models.SmallIntegerField(verbose_name=_('Maximum voltage'))
    max_amperage = models.SmallIntegerField(verbose_name=_('Maximum amperage'))
    max_electric_power = models.IntegerField(null=True, blank=True, verbose_name=_('Maximum electric power'))

    # If you want the default tariffs to be in use when needed use get_tariffs() instead of accessing tariff_ids
    tariff_ids = models.ManyToManyField('Tariff', related_name='connectors', blank=True, verbose_name=_('Tariffs'))

    terms_and_conditions = models.URLField(blank=True, default='', verbose_name=_('Terms and conditions'))

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))

    def __str__(self):
        return f'#{self.uid} - {self.get_standard_display()} - {self.power()}'

    def power(self):
        phases = Ocpi.POWERTYPE_PHASES.get(self.power_type, 1)
        return f'{int((self.max_electric_power or int(self.max_voltage) * int(self.max_amperage) * phases) / 1000)} kW'

    def tariff(self):
        return ','.join([t.price() for t in self.tariff_ids.all()])

    def tariff_html(self):
        return format_html('<br>'.join([t.link() for t in self.tariff_ids.all()]))

    def get_tariffs(self):
        # Fetch the Tariffs specified for this Connector or find a DefaultTariff in case no specific Tariffs
        from ocpi22.models.tariff import Tariff
        tariffs = self.tariff_ids.all() or Tariff.get_default_tariffs(self.standard)
        return tariffs

    def get_admin_url(self):
        return build_absolute_uri(util.reverse('admin:ocpi22_evse_change', args=(self.evse.pk,)))

    @property
    def issue_parent(self):
        # For showing the EVSE of this Connector in the issue list
        return self.evse


@receiver(pre_save, sender=Evse)
def evse_pre_save(sender, instance: Evse, *_args, raw, **_kwargs):
    if raw:
        return
    if not instance.evse_id:
        instance.evse_id = f'{instance.location.ocpi_master.country_code}*' \
                           f'{instance.location.ocpi_master.party_id}*E{instance.uid}'


@receiver(pre_save, sender=Connector)
def connector_pre_save(sender, instance, *_args, raw, **_kwargs):
    if raw:
        return
    connector: Connector = instance
    if not connector.uid:
        connector.uid = uuid.uuid4().hex
    if not connector.power_type:
        connector.power_type = Ocpi.POWERTYPES.get(connector.standard, 'AC_3_PHASE')


@receiver(post_save, sender=Connector)
def connector_post_save(sender, instance, *_args, raw, **kwargs):
    if raw:
        return
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
