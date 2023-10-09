from django.db import models
from django.utils.datetime_safe import datetime
from django.utils.translation import gettext as _

from django import forms
from django.core.exceptions import ValidationError
from gdpr_assist.admin import PersonalDataAdmin, PersonalData

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.models import User
from humanize import naturaltime

from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.logging import LogEntry, ChildEvent
from django.utils.html import format_html
from nested_admin.nested import NestedModelAdmin, NestedStackedInline, NestedTabularInline

from ocpi22.models.cdr import Cdr
from ocpi22.models.dynamic_price import DynamicPrice
from ocpi22.models.models import Facility, Capability
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.credentials import Credentials, CredentialsRole, Endpoint
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session, ChargingPeriod, CdrDimension
from ocpi22.models.tariff import PriceComponent, TariffElement, Tariff, DefaultTariffs
from ocpi22.models.token import Token
from ocpi22.msp.account import Account, Transaction
from ocpi22.msp.models import Authorization
from ocpi22.ocpi.partners import invalidate_partner_cache
from ocpiconnector.ocpi_identities import ocpi_identities, ocpi_platform, get_our_credentialsrole
from payment.models import Payment

admin.site.site_header = 'Roaming Admin'


class AdminUtilityMixin:
    def last_update(self, obj):
        return naturaltime(obj.last_updated)

    last_update.admin_order_field = 'last_updated'
    last_update.short_description = 'Last update'


class TokenAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = Token
    search_fields = ['ocpi_master__country_code', 'ocpi_master__party_id',
                     'uid', 'contract_id', 'visual_number', 'issuer', 'default_profile_type', 'type',
                     'customer__username', 'customer__first_name', 'customer__last_name']
    if ocpi_platform.is_emsp:
        list_display = ['valid', 'party_long', 'customer_name', 'uid', 'type', 'visual_number', 'balances',
                        'last_update']
    else:
        list_display = ['valid', 'party_long', 'uid', 'type', 'visual_number', 'last_update']
    list_display_links = ['uid']
    readonly_fields = ['ocpi_master', 'last_updated', 'created', 'type']

    def customer_name(self, obj) -> str:
        if not obj.customer:
            return 'N/A'
        from util import reverse
        return format_html(
            f'<a href="{reverse("admin:auth_user_change", args=[obj.customer.pk])}">'
            f'{obj.customer.first_name} {obj.customer.last_name}</a>'
        )

    fieldsets = [
        ('Customer', dict(
            fields=(
                ('customer',)
            )
        )),
        ('Identification', dict(
            fields=(
                'ocpi_master',
                ('uid', 'visual_number'),
                ('issuer', 'group_id'),
                'contract_id',
            )
        )),
        ('Specifics', dict(
            fields=(
                ('valid', 'type', 'whitelist'),
                ('language', 'default_profile_type'),
            )
        )),
        ('Dates', dict(
            fields=(
                ('created', 'last_updated')
            )
        ))
    ]

    def has_add_permission(self, request) -> bool:
        return Token.ocpi_object_owner in ocpi_identities or settings.ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_change_permission(self, request, obj: Token = None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        return (obj and obj.is_ours()) or settings.ALLOW_ADMIN_DELETE_AND_CHANGE

    def save_model(self, request, obj, form, change):
        """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
        our_msp_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.EMSP)
        try:
            if not settings.ALLOW_ADMIN_DELETE_AND_CHANGE and obj.ocpi_master \
                    and obj.ocpi_master != our_msp_credentialsrole:
                raise ValidationError('This is not our object')
        except Location.ocpi_master.RelatedObjectDoesNotExist:
            pass
        obj.ocpi_master = our_msp_credentialsrole
        if hasattr(obj, 'update_last_updated'):
            obj.update_last_updated()
        super().save_model(request, obj, form, change)

# Todo: Prevent Connector editing if not owner, get_readonly_fields() doesn't do it


class ConnectorAdminForm(forms.ModelForm):
    def clean_tariff_ids(self):
        data = self.cleaned_data.get('tariff_ids')
        if not data:
            raise ValidationError(
                _('Connector needs to have a Tariff selected, so that billing is possible'),
                code='missing'
            )
        return data


class ConnectorInline(NestedStackedInline):
    model = Connector
    form = ConnectorAdminForm

    fieldsets = [
        (None, dict(fields=[('uid', 'standard'), ('format', 'power_type'),
                            ('max_voltage', 'max_amperage'),
                            ('tariff_ids',), ('terms_and_conditions',)])),
    ]
    radio_fields = dict(
        format=admin.VERTICAL,
        power_type=admin.VERTICAL
    )
    autocomplete_fields = ['tariff_ids']

    def has_change_permission(self, request, obj: Evse = None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        # Todo: Admin should only be able to change owned Connectors
        if obj and hasattr(obj, 'location'):
            obj = obj.location
        return obj and hasattr(obj, 'is_ours') and obj.is_ours()

    def has_add_permission(self, request, obj=None) -> bool:
        return Location.ocpi_object_owner in ocpi_identities


class LocationAdmin(NestedModelAdmin, AdminUtilityMixin):
    class EvseInline(NestedStackedInline):

        model = Evse
        exclude = ['evse_id', 'last_updated']
        inlines = [ConnectorInline]
        autocomplete_fields = ['capabilities']

        formfield_overrides = {
            models.TextField: {'classes': 'form-control'},
        }

        def has_change_permission(self, request, obj=None) -> bool:
            if not super().has_change_permission(request, obj):
                return False
            return obj and obj.is_ours()

        def has_add_permission(self, request, obj=None) -> bool:
            return Location.ocpi_object_owner in ocpi_identities

    formfield_overrides = {
        models.TextField: {'classes': 'form-control'},
    }

    model = Location
    search_fields = ['ocpi_master__country_code', 'ocpi_master__party_id', 'uid', 'name', 'address', 'city',
                     'postal_code', 'state', 'country', 'parking_type']
    fieldsets = [
        ('Address', dict(
            # classes=('collapse',),  # Todo: Study collapsible accordions for admin
            fields=('uid', 'name', 'address', ('postal_code', 'city'), ('state', 'country'),
                    ('latitude', 'longitude', 'time_zone'),)
        )),
        ('Features', dict(
            fields=(('parking_type', 'facilities'),)
        )),
        ('Parties', dict(
            fields=(('operator', 'suboperator', 'owner'),)
        )),
    ]
    list_display = ['party_long', 'uid', 'publish', 'name', 'street_address', 'evse_list']
    list_display_links = ['uid']
    inlines = [EvseInline]
    autocomplete_fields = ['publish_allowed_to', 'facilities', 'operator', 'suboperator', 'owner']
    radio_fields = dict(
        parking_type=admin.VERTICAL
    )

    def has_change_permission(self, request, obj=None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        return obj and obj.is_ours()

    def has_add_permission(self, request) -> bool:
        return Location.ocpi_object_owner in ocpi_identities

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ['uid']
        return []

    def save_model(self, request, obj, form, change):
        """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
        our_cpo_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.CPO)
        try:
            if not settings.ALLOW_ADMIN_DELETE_AND_CHANGE and obj.ocpi_master \
                    and obj.ocpi_master != our_cpo_credentialsrole:
                raise ValidationError('This is not our object')
        except Location.ocpi_master.RelatedObjectDoesNotExist:
            pass
        obj.ocpi_master = our_cpo_credentialsrole
        obj.last_updated = datetime.utcnow
        super().save_model(request, obj, form, change)


class EvseAdminForm(forms.ModelForm):
    def clean_uid(self):
        # if Evse.objects.filter(uid=self.data['uid']).count():
        #     # Todo: Recognize if it's the same object, and allow it
        #     raise ValidationError(_('EVSE with this UID already exists in this or another Location'),)
        return self.cleaned_data["uid"]


class EvseAdmin(NestedModelAdmin, AdminUtilityMixin):
    form = EvseAdminForm
    model = Evse
    # Todo: In API, return most recent of last_updated and updated, but only owner can PATCH last_updated
    list_display = ['party_long', 'uid', 'location_link', 'status', 'connector_list', 'last_update']
    list_display_links = ['uid']
    inlines = [ConnectorInline]
    search_fields = ['evse_id', 'location__address', 'location__city', 'location__name', 'location__uid']
    # actions = ['start_charging', 'stop_charging']
    autocomplete_fields = ['capabilities', 'location']
    exclude = ['last_updated']
    list_filter = ['status']

    def get_queryset(self, request):
        return Evse.objects.select_related('location').all().order_by('-last_updated')

    @staticmethod
    def location_link(evse):
        from util import reverse
        return format_html("<a href='{url}'>{location}</a>",
                           url=reverse('admin:ocpi22_location_change', args=[evse.location.pk]),
                           location=str(evse.location))
    location_link.short_description = "Location"

    def last_update(self, obj):
        return naturaltime(obj.last_updated)

    last_update.admin_order_field = 'last_updated'
    last_update.short_description = 'Last update'

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ['last_updated']
        return []

    def has_change_permission(self, request, obj=None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        return not obj or (hasattr(obj, 'location') and obj.location.is_ours())

    # def save_model(self, request, obj, form, change):
    #     """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
    #     our_cpo_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.CPO)
    #     if not settings.ALLOW_ADMIN_DELETE_AND_CHANGE and obj.ocpi_master and obj.ocpi_master != our_cpo_credentialsrole:
    #         raise ValidationError('This is not our object')
    #     obj.ocpi_master = our_cpo_credentialsrole
    #     obj.last_updated = datetime.utcnow
    #     super().save_model(request, obj, form, change)


class BusinessDetailsAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = BusinessDetails
    list_display = ['name', 'website', 'logo', 'referenced_locations', 'referenced_credentials']
    search_fields = ['name', 'website']


class FacilityAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = Facility
    list_display = ['name', 'description']
    search_fields = ['name', 'description']

    def has_delete_permission(self, request, obj=None) -> bool:
        # Disable delete
        return False

    def has_add_permission(self, request) -> bool:
        # Disable add
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        # Disable change
        return False


class CapabilityAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = Capability
    list_display = ['name', 'description']
    search_fields = ['name', 'description']

    def has_delete_permission(self, request, obj=None) -> bool:
        # Disable delete
        return False

    def has_add_permission(self, request) -> bool:
        # Disable add
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        # Disable change
        return False


class CdrAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = Cdr
    ordering = ('-start_date_time',)
    if ocpi_platform.is_cpo:
        list_display = [
            'start_date_time',  # Todo: Show time everywhere in local timezone
            'billed_to', 'evse_id',
            'total_session_time', 'total_energy', 'total_cost',
        ]
    else:
        list_display = [
            'party_long',
            'start_date_time',  # Todo: Show time everywhere in local timezone
            'evse_id',
            'total_session_time', 'total_energy', 'total_cost',
        ]
    fieldsets = (
        ('Identification', dict(fields=(('ocpi_master', 'uid'),
                                        ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id')))),
        ('Location', dict(fields=(('cdr_location_name', 'cdr_location_city', 'cdr_location_country'),
                                  ('cdr_location_evse_uid', 'cdr_location_connector_id'),))),
        ('Delivery', dict(fields=(
            ('total_energy', 'auth_method'),
            ('total_cost_incl_vat', 'total_cost_excl_vat', 'currency'),))),
        ('Time period', dict(fields=(('start_date_time', 'end_date_time'), ))),
        ('Credited or not', dict(fields=(('credit', 'credit_reference'),))),
    )
    list_display_links = ['start_date_time']
    search_fields = ['session_id', 'uid', 'cdr_location_evse_id', 'cdr_location_name', 'cdr_location_city',
                     'cdr_location_country', 'cdr_token_uid', 'cdr_token_contract_id', 'billed_to']
    autocomplete_fields = ['tariffs']

    def has_add_permission(self, request) -> bool:
        # Disable add
        return settings.ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_change_permission(self, request, obj=None) -> bool:
        # Disable change
        return settings.ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_delete_permission(self, request, obj=None) -> bool:
        # Disable delete
        return settings.ALLOW_ADMIN_DELETE_AND_CHANGE


class SessionAdmin(NestedModelAdmin, AdminUtilityMixin):
    class ChargingPeriodInline(NestedStackedInline):
        model = ChargingPeriod

        class CdrDimensionInline(NestedTabularInline):
            model = CdrDimension

        inlines = [CdrDimensionInline]

    model = Session
    ordering = ['-updated']
    list_display = [
        'success',
        'status',
        'party_long',
        'last_update',  # Todo: Show time in local timezone
        'location',
        'kwh', 'cost',
    ]
    inlines = [ChargingPeriodInline]
    fieldsets = (
        ('Identification', dict(fields=(('ocpi_master',), ('uid', 'meter_id'),
                                        ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id'),
                                        ('location', 'evse', 'connector'),
                                        ))),
        ('Delivery',
         dict(fields=(('status', 'start_kwh', 'stop_kwh'), ('total_cost_incl_vat', 'total_cost_excl_vat', 'currency'),
                      ('message',),
                      ('auth_method', 'authorization_reference')))),
        ('Time period', dict(fields=(('start_date_time', 'end_date_time'), ))),
    )
    # Todo: Show only connectors for the selected evse

    list_display_links = ['status']
    search_fields = ['location__name', 'location__address', 'evse__evse_id', 'evse__uid', 'cdr_token_uid',
                     'uid', 'authorization_reference']
    readonly_fields = ['uid', 'ocpi_master']
    list_filter = ['status', 'connector__standard']

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def response_post_save_change(self, request, obj: Session):
        if obj.kwh:
            if obj.calculate_price():
                obj.save(update_fields=['total_cost_excl_vat', 'total_cost_incl_vat'])
            else:
                self.message_user(request, 'Cannot calculate cost for the session, because there are no Tariffs '
                                           'specified for the Connector. '
                                           'Please edit the Session or specify a default tariff.',
                                  level=messages.WARNING)

        return super().response_post_save_change(request, obj)


class TariffAdmin(NestedModelAdmin, AdminUtilityMixin):
    class ElementsInline(NestedStackedInline):
        class PriceComponentsInline(NestedTabularInline):
            model = PriceComponent
            exclude = ['dynamic_price_source']

            def has_change_permission(self, request, obj=None) -> bool:
                if not super().has_change_permission(request, obj):
                    return False
                if obj and hasattr(obj, 'tariff'):
                    obj = obj.tariff
                return (not obj or obj.is_ours()) \
                       or settings.ALLOW_ADMIN_DELETE_AND_CHANGE

            def has_add_permission(self, request, obj=None) -> bool:
                return Tariff.ocpi_object_owner in ocpi_identities or self.has_change_permission(request, obj)

        model = TariffElement
        inlines = [PriceComponentsInline]

        fieldsets = [
            ('Scope of the below price components', dict(
                fields=(
                    ('start_date', 'end_date'),
                    ('start_time', 'end_time'),
                    # ('min_kwh', 'max_kwh'),
                    # ('min_power', 'max_power'),
                    # ('min_current', 'max_current'),
                    ('min_duration', 'max_duration'),
                    ('day_of_week', ), # 'reservation'),
                )
            )),
        ]

        def has_change_permission(self, request, obj=None) -> bool:
            if not super().has_change_permission(request, obj):
                return False
            return (not obj or obj.is_ours()) \
                   or settings.ALLOW_ADMIN_DELETE_AND_CHANGE

        def has_add_permission(self, request, obj=None) -> bool:
            return Tariff.ocpi_object_owner in ocpi_identities or self.has_change_permission(request, obj)

    model = Tariff
    if ocpi_platform.is_cpo:
        list_display = ['uid', 'price', 'last_update']
    else:
        list_display = ['party_long', 'uid', 'price', 'last_update']
    list_display_links = ['uid']
    inlines = [ElementsInline]
    search_fields = ['uid']
    readonly_fields = ('last_updated',)

    fieldsets = [
        ('',
         dict(
             fields=(
                 ('ocpi_master',),
                 ('uid',),
                 ('currency',),
                 ('type',),
                 ('tariff_alt_url',),
             )
         )
         ),
        ('Price limits',
         dict(
             fields=(
                 ('min_price_excl_vat', 'min_price_incl_vat'),
                 ('max_price_excl_vat', 'max_price_incl_vat'),
             )
         )
         ),
    ]

    def get_queryset(self, _request):
        # Hide archived
        return Tariff.objects.exclude(archived=True)

    def get_readonly_fields(self, request, obj=None) -> list:
        readonly_fields = ['ocpi_master']
        if obj:
            readonly_fields.append('uid')
        return readonly_fields

    def has_change_permission(self, request, obj=None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        return (obj and obj.is_ours()) \
               or settings.ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request) -> bool:
        return Tariff.ocpi_object_owner in ocpi_identities

    def save_model(self, request, obj, form, change):
        """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
        our_cpo_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.CPO)
        try:
            if not settings.ALLOW_ADMIN_DELETE_AND_CHANGE and obj.ocpi_master \
                    and obj.ocpi_master != our_cpo_credentialsrole:
                raise ValidationError('This is not our object')
        except Location.ocpi_master.RelatedObjectDoesNotExist:
            pass
        obj.ocpi_master = our_cpo_credentialsrole
        obj.last_updated = datetime.utcnow
        super().save_model(request, obj, form, change)


class CredentialsAdmin(admin.ModelAdmin, AdminUtilityMixin):
    class CredentialRolesInline(admin.TabularInline):
        model = CredentialsRole

    class EndpointsInline(admin.TabularInline):
        model = Endpoint

    model = Credentials
    list_display = ['name', 'valid', 'responding', 'last_update']
    readonly_fields = ['theirs_base64', 'ours_base64', 'last_updated', 'created', 'last_connection']
    inlines = [CredentialRolesInline, EndpointsInline]
    search_fields = ['roles__party_id', 'roles__country_code', 'ours', 'theirs', 'token_a',
                     'roles__business_details__name']
    list_display_links = ['name']

    def has_add_permission(self, request, obj=None):
        return settings.PREMIUM

    def has_change_permission(self, request, obj=None):
        return settings.PREMIUM

    def last_update(self, obj):
        return naturaltime(obj.last_connection)

    last_update.admin_order_field = 'last_connection'
    last_update.short_description = 'Last connection'


@admin.register(CredentialsRole)
class CredentialsRoleAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = CredentialsRole
    list_display = ['party_long', 'role', 'business_details']
    fields = ['business_details', 'agreed_parties']
    list_filter = ['role']
    autocomplete_fields = ['agreed_parties']
    search_fields = ['business_details__name', 'business_details__website',
                     'agreed_parties__country_code', 'agreed_parties__party_id']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj and change and hasattr(obj, 'ocpi_master'):
            party = obj.ocpi_master.party
            invalidate_partner_cache(party)


@admin.register(DefaultTariffs)
class DefaultTariffsAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = DefaultTariffs
    list_display = ['standard', 'tariff_list']
    autocomplete_fields = ['tariffs']


@admin.register(DynamicPrice)
class DynamicPriceAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = DynamicPrice
    ordering = ['-start_datetime']
    list_display = ['dynamic_price_source', 'price', 'start_datetime', 'end_datetime']
    list_filter = ['dynamic_price_source']
    search_fields = ['dynamic_price_source']


# admin.site.unregister(User)
admin.site.unregister(PersonalData)


@admin.register(PersonalData)
class MyPersonalDataAdmin(PersonalDataAdmin, AdminUtilityMixin):
    change_list_template = "admin/gdpr_assist/personaldata/change_list.html"

    # def changelist_view(self, *args, **kwargs):
    #     result = super().changelist_view(*args, **kwargs)
    #     return result


# @admin.register(User)
class UserAdmin(NestedModelAdmin, AdminUtilityMixin):
    class AccountAdmin(NestedStackedInline):
        class TransactionInline(NestedTabularInline):
            model = Transaction

        inlines = [TransactionInline]
        model = Account
        ordering = ['customer']
        search_fields = ('customer__username', 'customer__first_name', 'customer__last_name')

    model = User
    inlines = [AccountAdmin]
    list_display = ('username', 'first_name', 'last_name', 'balances', 'app_token_ids')
    search_fields = ('username', 'first_name', 'last_name')
    fields = ('first_name', 'last_name', 'email', 'is_active')

    def balances(self, obj):
        if not obj or not obj.accounts.exists():
            return '-'
        return format_html(
            "<br>".join(
                [f'{account.balance}{account.currency}' for account in obj.accounts.all()]
            )
        )

    def app_token_ids(self, obj):
        return format_html(
            "<br>".join(
                [account.app_token_id for account in obj.accounts.all()]
            )
        )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = Payment
    exclude = []
    list_display = ('status', 'email', 'amount', 'currency', 'created')
    search_fields = ('amount', 'payment_method__customer__user__email')

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Authorization)
class AuthorizationAdmin(admin.ModelAdmin, AdminUtilityMixin):
    model = Authorization
    exclude = []
    list_display = ('authorization_reference', 'session', 'max_price', 'created')
    search_fields = ('authorization_reference', 'session__uid')

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LogEntry)
class LogEntryAdmin(NestedModelAdmin, AdminUtilityMixin):
    class ChildEventInline(NestedTabularInline):
        model = ChildEvent
        include = ['level', 'text', 'created']

        def has_change_permission(self, request, obj=None):
            return False

        def has_add_permission(self, request, obj=None):
            return False

        def has_delete_permission(self, request, obj=None):
            return True

    inlines = [ChildEventInline]
    model = LogEntry
    exclude = []
    list_display = ('topic', 'updated')
    ordering = ['-updated']
    search_fields = ['events__text', 'topic']

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return True


admin.site.register(Token, TokenAdmin)
admin.site.register(Location, LocationAdmin)
admin.site.register(Evse, EvseAdmin)
admin.site.register(BusinessDetails, BusinessDetailsAdmin)
admin.site.register(Facility, FacilityAdmin)
admin.site.register(Capability, CapabilityAdmin)
admin.site.register(Tariff, TariffAdmin)
admin.site.register(Cdr, CdrAdmin)
admin.site.register(Session, SessionAdmin)
admin.site.register(Credentials, CredentialsAdmin)
