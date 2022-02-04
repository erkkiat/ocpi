import uuid
from copy import deepcopy

from django.conf import settings
from django.db import models
from django.db.models import QuerySet
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils.html import format_html
from rest_framework.reverse import reverse

from ocpi22.util import ModelUtilMixin, format_currency
from ocpi22.ocpi_util import OcpiModule, Ocpi
from ocpiconnector.settings import COUNTRY_CODE, PARTY_ID


class Tariff(models.Model, ModelUtilMixin, OcpiModule):
    ocpi_serializer_class = 'ocpi22.api.TariffSerializer'
    ocpi_module_name = Ocpi.Modules.TARIFFS
    send_updates_to = ['EMSP', 'NAP', 'NSP', 'HUB']

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

    upper_case_fields = ('country_code', 'party_id', 'currency', 'uid')

    # This object has been archived, but there may be references to it
    archived = models.BooleanField(default=False)

    # ISO-3166 alpha-2 country code of the CPO that owns this Location
    country_code = models.CharField(max_length=2, default=COUNTRY_CODE)

    # CPO ID of the CPO that 'owns' this Tariff (following the ISO-15118 standard)
    party_id = models.CharField(max_length=3, default=PARTY_ID)

    # Uniquely identifies the tariff within the CPO’s platform (and suboperator platforms)
    uid = models.CharField(max_length=36)

    # ISO-4217 code of the currency of this tariff
    currency = models.CharField(max_length=3, choices=Ocpi.CURRENCY_CHOICES, default=settings.DEFAULT_CURRENCY)

    # Defines the type of the tariff. This allows for distinction in case of given Charging Preferences.
    # When omitted, this tariff is valid for all sessions.
    TYPE_CHOICES = (
        # Used to describe that a Tariff is valid when ad-hoc payment is used at
        # the Charge Point (for example: Debit or Credit card payment terminal).
        ('AD_HOC_PAYMENT', 'Ad hoc payment'),

        # Used to describe that a Tariff is valid when Charging Preference: CHEAP is set for the session.
        ('PROFILE_CHEAP', 'CHEAP profile'),

        # Used to describe that a Tariff is valid when Charging Preference: FAST is set for the session.
        ('PROFILE_FAST', 'FAST profile'),

        # Used to describe that a Tariff is valid when Charging Preference: GREEN is set for the session.
        ('PROFILE_GREEN', 'GREEN profile'),

        # Used to describe that a Tariff is valid when using an RFID, without any Charging Preference,
        # or when Charging Preference: REGULAR is set for the session.
        ('REGULAR', 'Regular profile'),
    )

    type = models.CharField(max_length=14, choices=TYPE_CHOICES, blank=True, default='')

    # URL to a web page that contains an explanation of the tariff information in human readable form.
    tariff_alt_url = models.URLField(blank=True, default='')

    # When this field is set, a Charging Session with this tariff will at least cost this amount.
    # This is different from a FLAT fee (Start Tariff, Transaction Fee), as a FLAT fee is
    # a fixed amount that has to be paid for any Charging Session.
    # A minimum price indicates that when the cost of a Charging Session is lower than this amount,
    # the cost of the Session will be equal to this amount. (Also see note below)

    # min_price
    # max_price

    # The OCPI field writable and maintained by object owner
    last_updated = models.DateTimeField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs) -> None:
        self.change_fields_to_upper_case()
        super(self.__class__, self).save(*args, **kwargs)

    def __str__(self):
        return self.uid

    def price(self):
        """Format the price components in a readable form"""
        # noinspection PyUnresolvedReferences
        components = [
            str(pc)
            for pc in [
                element
                for element in self.tariff_elements.all()
            ]
        ]
        # noinspection PyUnresolvedReferences
        return f"{' + '.join(components or [f'{self.uid}'])} -- {self.get_type_display()}"

    def link(self):
        url = reverse('admin:ocpi22_tariff_change', args=[self.pk])
        # noinspection PyUnresolvedReferences
        return format_html(
            f"<a href='{url}'>{self.price()}</a>"
        )

    def get_absolute_url(self):
        return reverse('tariff-by-id', args=[self.country_code, self.party_id, self.uid])

    def references(self):
        if settings.DEBUG:
            from ocpi22.models.cdr import Cdr
            # noinspection PyUnresolvedReferences
            return Cdr.objects.filter(tariffs=self).count()
        return 'N/A'

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
    def make_copies(cls, tariffs):
        result = []
        for t in tariffs:
            result.append(cls.make_copy(t))
        return result

    # noinspection PyUnresolvedReferences
    @classmethod
    def get_default_tariffs(cls, standard) -> QuerySet:
        try:
            default_tariffs = DefaultTariffs.objects.get(standard=standard)
            return default_tariffs.tariffs.all()
        except DefaultTariffs.DoesNotExist:
            return DefaultTariffs.objects.none()


class TariffElement(models.Model, ModelUtilMixin):
    tariff = models.ForeignKey(Tariff, related_name='tariff_elements', on_delete=models.CASCADE)

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return ", ".join([str(pc) for pc in self.price_components.all()])


class PriceComponent(models.Model, ModelUtilMixin):
    # List of price components that describe the pricing of a tariff.

    TYPE_CHOICES = (
        # Defined in kWh, step_size multiplier: 1 Wh
        ('ENERGY', 'Wh'),

        # Flat fee without unit for step_size
        ('FLAT', 'Flat'),

        # Time not charging: defined in hours, step_size multiplier: 1 second
        # ('PARKING_TIME', 'Parking seconds'),
        # Todo: Implement PARKING_TIME PriceComponent

        # Time charging: defined in hours, step_size multiplier: 1 second
        # Can also be used in combination with a RESERVATION restriction to describe the price of the reservation time.
        ('TIME', 'Charging seconds'),
    )
    type = models.CharField(max_length=12, choices=TYPE_CHOICES)

    # Price /unit (excl. VAT) for this tariff dimension.
    price = models.FloatField()

    # Applicable VAT percentage for this tariff dimension. If omitted, no VAT is applicable.
    # Not providing a VAT is different from 0% VAT, which would be a value of 0.0 here.
    vat = models.FloatField(blank=True, null=True)

    # Minimum amount to be billed. This unit will be billed in this step_size blocks.
    # Amounts that are less then this step_size are rounded up to the given step_size.
    # For example: if type is TIME and step_size has a value of 300, then time will be billed in blocks of 5 minutes.
    # If 6 minutes were used, 10 minutes (2 blocks of step_size) will be billed.
    step_size = models.IntegerField()

    @property
    def tariff(self):
        return self.tariff_element.tariff

    tariff_element = models.ForeignKey(TariffElement, related_name='price_components', on_delete=models.CASCADE)

    def _format_step_and_type(self):
        t = self.type
        s = self.step_size
        if t == 'ENERGY':
            if s == 1000:
                return '/ kWh'
            else:
                return f'/ {s} Wh'
        elif t == 'FLAT':
            return 'flat'
        elif t == 'TIME':
            if s == 60:
                return '/ minute'
            elif s == 3600:
                return '/ hour'
            else:
                return f'/ {s} seconds'
        elif t == 'PARKING_TIME':
            if s == 60:
                return '/ parking minute'
            elif s == 3600:
                return '/ hour parking'
            else:
                return f'/ {s} parking seconds'
        # noinspection PyUnresolvedReferences
        return f'/ {s} {self.get_type_display()}'

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'{format_currency(self.price or 0.0, self.tariff.currency)} {self._format_step_and_type()}'


class DefaultTariffs(models.Model):
    class Meta:
        verbose_name_plural = 'default tariffs'

    standard = models.CharField(max_length=21, choices=Ocpi.STANDARD_CHOICES, unique=True)
    tariffs = models.ManyToManyField(Tariff, related_name='default_standards')

    def __str__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.get_standard_display()} defaults to tariffs {", ".join(str(t) for t in self.tariffs.all())}'

    def tariff_list(self):
        return f'{", ".join(str(t) for t in self.tariffs.all())}'


@receiver(pre_save, sender=Tariff)
def tariff_pre_save(sender, instance, *_args, **_kwargs):
    tariff: Tariff = instance
    if not tariff.uid:
        tariff.uid = uuid.uuid4().hex


@receiver(post_save, sender=PriceComponent)
def price_component_post_save(sender, instance: PriceComponent, *_args, **_kwargs):
    tariff = instance.tariff
    # Do not update last_updated here, only owner does that
    tariff.save()