import ocpi22.logging as logging

import requests
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.html import format_html
from icecream import ic
from nested_admin.nested import NestedModelAdmin, NestedStackedInline, NestedTabularInline
from requests import Response
from rest_framework import exceptions
from rest_framework.exceptions import APIException

from ocpi22.commands.commands import send_start_command, send_stop_command
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
from ocpi22.sessions.util import get_active_sessions
from ocpi22.tokens.util import get_admin_token
from ocpiconnector.ocpi_identities import ocpi_identities, ocpi_platform

ALLOW_ADMIN_DELETE_AND_CHANGE = False


class TokenAdmin(admin.ModelAdmin):
    model = Token
    search_fields = ['party_id', 'uid', 'contract_id', 'visual_number', 'issuer', 'default_profile_type', 'type',
                     'customer__username', 'customer__first_name', 'customer__last_name']
    if ocpi_platform.is_emsp:
        list_display = ['object_owner', 'valid', 'customer_name', 'uid', 'type', 'visual_number', 'balances',
                        'last_updated']
    else:
        list_display = ['object_owner', 'valid', 'uid', 'type', 'visual_number', 'last_updated']
    list_display_links = ['uid']
    readonly_fields = ['country_code', 'party_id']

    def customer_name(self, obj) -> str:
        if not obj.customer:
            return 'N/A'
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
                ('country_code', 'party_id'),
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
    ]

    # def has_delete_permission(self, request, obj=None) -> bool:
    #     # Disable delete
    #     return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request) -> bool:
        # ic(Token.ocpi_object_owner, Token.ocpi_object_owner in ocpi_identities)
        return Token.ocpi_object_owner in ocpi_identities or ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_change_permission(self, request, obj: Token = None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        # user: User = request.user
        # ic(user.get_user_permissions())
        # if not user.has_perm('ocpi22.change_token'):
        #     return False
        return (obj and obj.is_ours()) or ALLOW_ADMIN_DELETE_AND_CHANGE


# Todo: Prevent Connector editing if not owner, get_readonly_fields() doesn't do it


class ConnectorInline(NestedStackedInline):
    model = Connector

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

    # def get_readonly_fields(self, request, obj=None):
    #     if obj:
    #         return ['uid']
    #     return []

    def has_change_permission(self, request, obj: Evse = None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        # Todo: Admin should only be able to change owned Connectors
        # ic(obj)
        if obj and hasattr(obj, 'location'):
            obj = obj.location
        return obj and hasattr(obj, 'is_ours') and obj.is_ours()

    def has_add_permission(self, request, obj=None) -> bool:
        # ic(Token.ocpi_object_owner, Token.ocpi_object_owner in ocpi_identities)
        return Location.ocpi_object_owner in ocpi_identities

    # def has_delete_permission(self, request, obj=None) -> bool:
    #     return False


class LocationAdmin(NestedModelAdmin):
    class EvseInline(NestedStackedInline):

        model = Evse
        exclude = ['evse_id']
        inlines = [ConnectorInline]
        autocomplete_fields = ['capabilities']
        radio_fields = dict(
            status=admin.VERTICAL
        )

        def has_change_permission(self, request, obj=None) -> bool:
            if not super().has_change_permission(request, obj):
                return False
            return obj and obj.is_ours()

        # def has_delete_permission(self, request, obj=None) -> bool:
        #     return ALLOW_ADMIN_DELETE_AND_CHANGE

        def has_add_permission(self, request, obj=None) -> bool:
            # ic(Token.ocpi_object_owner, Token.ocpi_object_owner in ocpi_identities)
            return Location.ocpi_object_owner in ocpi_identities

        # def get_readonly_fields(self, request, obj=None) -> list:
        #     if obj:
        #         return ['uid']
        #     return []

    model = Location
    search_fields = ['country_code', 'party_id', 'uid', 'name', 'address', 'city',
                     'postal_code', 'state', 'country', 'parking_type']
    # fields = ['uid', 'publish', 'publish_allowed_to',
    #           ('name', 'address'), ('postal_code', 'city'), ('state', 'country'), ('latitude', 'longitude'),
    #           ('parking_type', 'facilities'), ('operator', 'suboperator', 'owner'), 'time_zone']
    fieldsets = [
        (None, dict(fields=('uid', 'publish', 'publish_allowed_to'))),
        ('Address', dict(
            fields=('name', 'address', ('postal_code', 'city'), ('state', 'country'),
                    ('latitude', 'longitude', 'time_zone'),)
        )),
        ('Features', dict(
            fields=(('parking_type', 'facilities'),)
        )),
        ('Parties', dict(
            fields=(('operator', 'suboperator', 'owner'),)
        )),
    ]
    list_display = ['party', 'uid', 'publish', 'name', 'street_address', 'evse_list']
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

    # def has_delete_permission(self, request, obj=None) -> bool:
    #     return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request) -> bool:
        # ic(Token.ocpi_object_owner, Token.ocpi_object_owner in ocpi_identities)
        return Location.ocpi_object_owner in ocpi_identities

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ['uid']
        return []


class EvseAdmin(NestedModelAdmin):
    model = Evse
    # Todo: In API, return most recent of last_updated and updated, but only owner can PATCH last_updated
    list_display = ['object_owner', 'evse_id', 'location_url', 'status', 'connector_list']
    inlines = [ConnectorInline]
    search_fields = ['evse_id', 'location__address', 'location__city', 'location__name']
    actions = ['start_charging', 'stop_charging']
    autocomplete_fields = ['capabilities', 'location']

    def get_queryset(self, request):
        # noinspection PyUnresolvedReferences
        return Evse.objects.select_related('location').all().order_by('-last_updated')

    @staticmethod
    def location_url(evse):
        return format_html("<a href='{url}'>{location}</a>",
                           url=reverse('admin:ocpi22_location_change', args=[evse.location.pk]),
                           location=str(evse.location))

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ['uid', 'last_updated']
        return []

    def has_change_permission(self, request, obj=None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        return not obj or (hasattr(obj, 'location') and obj.location.is_ours())

    # def has_delete_permission(self, request, obj=None) -> bool:
    #     return ALLOW_ADMIN_DELETE_AND_CHANGE

    # def delete_model(self, request, obj):
    #     obj.status = 'REMOVED'
    #     obj.save()

    location_url.short_description = "Location"

    @admin.action(description='Start charging')
    def start_charging(self, request, queryset):
        evse: Evse
        for evse in queryset:
            try:
                response = send_start_command(request, evse, get_admin_token())
                data = response.json()
                level = messages.SUCCESS if data.get('status_code') == 1000 else messages.ERROR
                data = data.get('data', data)
                self.message_user(request, f"Response: {data.get('message')}", level=level)
            except (APIException, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logging.error(f"{settings.HOSTNAME}: admin:start_charging(), result: {e}")
                self.message_user(request, f'Unable to start charging at {evse.location}. {e}',
                                  level=messages.ERROR)

    @admin.action(description='Stop all active charging sessions')
    def stop_charging(self, request, queryset):
        evse: Evse
        for evse in queryset:
            active_sessions = get_active_sessions(evse)
            if not active_sessions.count():
                self.message_user(request, f'There are no active sessions at Evse {evse.evse_id}.',
                                  level=messages.WARNING)
            for session in active_sessions.all():
                try:
                    response: Response = send_stop_command(session)
                    if response:
                        self.message_user(request, f'Stopping charging at {evse.location}, '
                                                   f'response: {response.status_code} - '
                                                   f'{response.reason if hasattr(response, "reason") else "Ok"}')
                    else:
                        self.message_user(request, f'Unable to stop charging at {evse.location}.',
                                          level=messages.ERROR)

                except exceptions.APIException as e:
                    self.message_user(request, f'Unable to stop charging at {evse.location}. {e}',
                                      level=messages.ERROR)


class BusinessDetailsAdmin(admin.ModelAdmin):
    model = BusinessDetails
    list_display = ['name', 'website', 'logo', 'referenced_locations', 'referenced_credentials']
    search_fields = ['name', 'website']


class FacilityAdmin(admin.ModelAdmin):
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


class CapabilityAdmin(admin.ModelAdmin):
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


class CdrAdmin(admin.ModelAdmin):
    model = Cdr
    ordering = ('-start_date_time',)
    if ocpi_platform.is_cpo:
        list_display = [
            'token_id',
            'start_date_time',  # Todo: Show time in local timezone
            'billed_to', 'evse_id', 'auth_method',
            'total_session_time', 'total_energy', 'total_cost',
            'uid',
        ]
    else:
        list_display = [
            'token_id',
            'start_date_time',  # Todo: Show time in local timezone
            'evse_id', 'auth_method',
            'total_session_time', 'total_energy', 'total_cost',
            'uid',
        ]
    fieldsets = (
        ('Identification', dict(fields=(('country_code', 'party_id', 'uid'),
                                        ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id')))),
        ('Location', dict(fields=(('cdr_location_name', 'cdr_location_city', 'cdr_location_country'),
                                  ('cdr_location_evse_uid', 'cdr_location_connector_id'),))),
        ('Delivery', dict(fields=(
            ('total_energy', 'total_time', 'auth_method'),
            ('total_cost_incl_vat', 'total_cost_excl_vat', 'currency'),))),
        ('Time period', dict(fields=(('start_date_time', 'end_date_time'), 'last_updated'))),
        ('Credited or not', dict(fields=(('credit', 'credit_reference'),))),
    )
    # list_filter = ['party_id', 'auth_method', 'credit']
    list_display_links = ['start_date_time']
    search_fields = ['party_id', 'country_code', 'session_id', 'uid', 'cdr_location_evse_id', 'cdr_location_name',
                     'billed_to']
    autocomplete_fields = ['tariffs']

    # def has_delete_permission(self, request, obj=None) -> bool:
    #     # Disable delete
    #     return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request) -> bool:
        # Disable add
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_change_permission(self, request, obj=None) -> bool:
        # Disable change
        return ALLOW_ADMIN_DELETE_AND_CHANGE


class SessionAdmin(NestedModelAdmin):
    class ChargingPeriodInline(NestedStackedInline):
        model = ChargingPeriod

        class CdrDimensionInline(NestedTabularInline):
            model = CdrDimension

        inlines = [CdrDimensionInline]

    model = Session
    ordering = ['-start_date_time']
    if ocpi_platform.is_cpo:
        list_display = [
            'status',
            'token_id',
            'start_date_time',  # Todo: Show time in local timezone
            'evse', 'connector',
            'billed_to',
            'total_time', 'kwh', 'cost',
            'internal_reference',
            'uid',
        ]
    else:
        list_display = [
            'status',
            'token_id',
            'start_date_time',  # Todo: Show time in local timezone
            'evse', 'connector',
            'total_time', 'kwh', 'cost',
            'uid',
        ]
    inlines = [ChargingPeriodInline]
    fieldsets = (
        ('Identification', dict(fields=(('country_code', 'party_id'), ('uid', 'meter_id'),
                                        ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id'),
                                        ('location', 'evse', 'connector'),
                                        ))),
        ('Delivery',
         dict(fields=(('status', 'start_kwh', 'stop_kwh'), ('total_cost_incl_vat', 'total_cost_excl_vat', 'currency'),
                      ('message',),
                      ('auth_method', 'authorization_reference')))),
        ('Time period', dict(fields=(('start_date_time', 'end_date_time'), 'last_updated'))),
    )
    # Todo: Show only connectors for the selected evse

    # fields = (
    #     ('start_date_time', 'end_date_time'),
    #     ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id'),
    #     ('status', 'kwh'),
    #     ('total_cost_excl_vat', 'total_cost_incl_vat', 'currency')
    # )
    list_display_links = ['start_date_time']
    search_fields = ['location__name', 'location__address', 'evse__evse_id', 'evse__uid', 'party_id', 'cdr_token_uid',
                     'uid', 'authorization_reference']
    # list_filter = ['status', 'party_id',]
    readonly_fields = ['uid', 'party_id', 'country_code']

    # def formfield_for_foreignkey(self, db_field, request, **kwargs):
    #     if db_field.name == "connector":
    #         kwargs["queryset"] = Connector.objects.filter(evse=??)
    #     return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # def get_readonly_fields(self, request, obj=None) -> list:
    #     if obj:
    #         return [
    #             'country_code', 'party_id', 'meter_id',
    #             'authorization_reference', 'uid', 'auth_method',
    #             'cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id',
    #             'location', 'evse', 'start_date_time', 'total_cost_incl_vat', 'total_cost_excl_vat',
    #         ]
    #     return []

    # def has_delete_permission(self, request, obj=None) -> bool:
    #     # Disable delete except for invalid sessions
    #     return (obj and obj.status == 'INVALID') or ALLOW_ADMIN_DELETE_AND_CHANGE

    # def has_change_permission(self, request, obj: Session = None) -> bool:
    #     if obj and obj.status == Session.COMPLETED and obj.total_cost_excl_vat:
    #         return False
    #     return (obj and obj.is_ours()) or ALLOW_ADMIN_DELETE_AND_CHANGE

    # def has_add_permission(self, request) -> bool:
    #     # Disable add
    #     return False

    def response_post_save_change(self, request, obj: Session):
        if obj.kwh:
            if obj.calculate_price() == True:
                obj.save(update_fields=['total_cost_excl_vat', 'total_cost_incl_vat'])
            else:
                self.message_user(request, 'Cannot calculate cost for the session, because there are no Tariffs '
                                           'specified for the Connector. '
                                           'Please edit the Session or specify a default tariff.',
                                  level=messages.WARNING)

        return super().response_post_save_change(request, obj)


class TariffAdmin(NestedModelAdmin):
    class ElementsInline(NestedStackedInline):
        class PriceComponentsInline(NestedTabularInline):
            model = PriceComponent

            def has_change_permission(self, request, obj=None) -> bool:
                if not super().has_change_permission(request, obj):
                    return False
                if obj and hasattr(obj, 'tariff'):
                    obj = obj.tariff
                return (not obj or obj.is_ours()) \
                       or ALLOW_ADMIN_DELETE_AND_CHANGE

            def has_add_permission(self, request, obj=None) -> bool:
                return Tariff.ocpi_object_owner in ocpi_identities or self.has_change_permission(request, obj)

        model = TariffElement
        inlines = [PriceComponentsInline]

        fieldsets = [
            ('Scope of the below price components', dict(
                fields=(
                    ('start_date', 'end_date'),
                    ('start_time', 'end_time'),
                    ('min_kwh', 'max_kwh'),
                    ('min_power', 'max_power'),
                    ('min_current', 'max_current'),
                    ('min_duration', 'max_duration'),
                    ('day_of_week', 'reservation'),
                )
            )),
        ]

        def has_change_permission(self, request, obj=None) -> bool:
            if not super().has_change_permission(request, obj):
                return False
            return (not obj or obj.is_ours()) \
                   or ALLOW_ADMIN_DELETE_AND_CHANGE

        def has_add_permission(self, request, obj=None) -> bool:
            return Tariff.ocpi_object_owner in ocpi_identities or self.has_change_permission(request, obj)

    model = Tariff
    list_display = [
        # 'archived',
        'object_owner', 'uid', 'price', 'references'
    ]
    list_display_links = ['uid']
    inlines = [ElementsInline]
    search_fields = ['uid']
    # list_filter = ['archived']
    radio_fields = dict(type=admin.HORIZONTAL)
    # exclude = ['archived', 'last_updated']
    fieldsets = [
        ('',
         dict(
             fields=(
                 ('country_code', 'party_id'),
                 ('uid', 'currency'),
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
        # noinspection PyUnresolvedReferences
        return Tariff.objects.exclude(archived=True)

    def get_readonly_fields(self, request, obj=None) -> list:
        readonly_fields = ['country_code', 'party_id']
        if obj:
            readonly_fields.append('uid')
        return readonly_fields

    def has_change_permission(self, request, obj=None) -> bool:
        if not super().has_change_permission(request, obj):
            return False
        return (obj and obj.is_ours()) \
               or ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request) -> bool:
        return Tariff.ocpi_object_owner in ocpi_identities


class CredentialsAdmin(admin.ModelAdmin):
    class CredentialRolesInline(admin.TabularInline):
        model = CredentialsRole

    class EndpointsInline(admin.TabularInline):
        model = Endpoint

    model = Credentials
    list_display = ['valid', 'party', 'last_connection', 'connection_state', 'token_a_base64', 'ours_base64',
                    'theirs_base64']
    readonly_fields = ['theirs_base64', 'last_updated', 'created', 'last_connection']
    inlines = [CredentialRolesInline, EndpointsInline]
    search_fields = ['roles__party_id', 'roles__country_code', 'ours', 'theirs', 'token_a']
    list_display_links = ['token_a_base64']


@admin.register(CredentialsRole)
class CredentialsRoleAdmin(admin.ModelAdmin):
    model = CredentialsRole
    list_display = ['party', 'role', 'business_details']


@admin.register(DefaultTariffs)
class DefaultTariffsAdmin(admin.ModelAdmin):
    model = DefaultTariffs
    list_display = ['standard', 'tariff_list']
    autocomplete_fields = ['tariffs']


@admin.register(DynamicPrice)
class DynamicPriceAdmin(admin.ModelAdmin):
    model = DynamicPrice
    ordering = ['-start_datetime']
    list_display = ['dynamic_price_source', 'price', 'start_datetime', 'end_datetime']
    list_filter = ['dynamic_price_source']
    search_fields = ['dynamic_price_source']


# admin.site.unregister(User)


# @admin.register(User)
class UserAdmin(NestedModelAdmin):
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
