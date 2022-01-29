from django.conf import settings
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from nested_admin.nested import NestedModelAdmin, NestedStackedInline, NestedTabularInline
from requests import Response
from rest_framework import exceptions

from ocpi22.commands import send_start_command
from ocpi22.models.cdr import Cdr
from ocpi22.models.models import BusinessDetails, Facility, Capability
from ocpi22.models.credentials import Credentials, CredentialsRole, Endpoint
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.tariff import PriceComponent, TariffElement, Tariff, DefaultTariffs
from ocpi22.models.token import Token
from ocpi22.util import ModelUtilMixin
from ocpi22.tokens import get_admin_token

ALLOW_ADMIN_DELETE_AND_CHANGE = False


class TokenAdmin(admin.ModelAdmin):
    model = Token
    search_fields = ['party_id', 'uid', 'contract_id', 'visual_number', 'issuer', 'default_profile_type', 'type']
    list_display = ['party', 'valid', 'uid', 'type', 'visual_number', 'last_updated']
    list_display_links = ['uid']
    readonly_fields = ['country_code', 'party_id']

    def has_delete_permission(self, request, obj=None) -> bool:
        # Disable delete
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    # def has_add_permission(self, request, obj=None):
    #     # Disable add
    #     return False

    def has_change_permission(self, request, obj: Token = None) -> bool:
        return obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID


# Todo: Prevent Connector editing if not owner, get_readonly_fields() doesn't do it


class ConnectorInline(NestedStackedInline):
    model = Connector

    fieldsets = [
        (None, dict(fields=[('uid', 'standard', 'format', 'power_type')])),
        (None, dict(fields=[('max_voltage', 'max_amperage')])),
        (None, dict(fields=[('tariff_ids', 'terms_and_conditions')])),
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

    def has_change_permission(self, request, obj: ModelUtilMixin = None) -> bool:
        # Todo: Admin should only be able to change owned Connectors
        # ic(obj)
        return hasattr(obj, 'is_ours') and obj.is_ours()

    def has_add_permission(self, request, obj) -> bool:
        return self.has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


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
            return obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID

        def has_delete_permission(self, request, obj=None) -> bool:
            return ALLOW_ADMIN_DELETE_AND_CHANGE

        def get_readonly_fields(self, request, obj=None) -> list:
            if obj:
                return ['uid']
            return []

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
        return obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID

    def has_delete_permission(self, request, obj=None) -> bool:
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ['uid']
        return []


class EvseAdmin(NestedModelAdmin):
    model = Evse
    exclude = ['last_updated']
    # Todo: In API, return most recent of last_updated and updated, but only owner can PATCH last_updated
    list_display = ['party', 'evse_id', 'location_url', 'status', 'connector_list']
    inlines = [ConnectorInline]
    search_fields = ['evse_id', 'location__address', 'location__city', 'location__name']
    actions = ['start_charging']
    autocomplete_fields = ['capabilities', 'location']

    def get_queryset(self, request):
        # noinspection PyUnresolvedReferences
        return Evse.objects.select_related('location').all()

    @staticmethod
    def location_url(evse):
        return format_html("<a href='{url}'>{location}</a>",
                           url=reverse('admin:ocpi22_location_change', args=[evse.location.pk]),
                           location=str(evse.location))

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ['uid']
        return []

    def has_change_permission(self, request, obj=None) -> bool:
        return obj and obj.location.country_code == settings.COUNTRY_CODE and obj.location.party_id == settings.PARTY_ID

    def has_delete_permission(self, request, obj=None) -> bool:
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    # def delete_model(self, request, obj):
    #     obj.status = 'REMOVED'
    #     obj.save()

    location_url.short_description = "Location"

    @admin.action(description='Start charging')
    def start_charging(self, request, queryset):
        evse: Evse
        for evse in queryset:
            try:
                response: Response = send_start_command(request, evse, get_admin_token())
                if response:
                    self.message_user(request, f'Starting charging at {evse.location}, '
                                               f'response: {response.status_code} - '
                                               f'{response.reason if hasattr(response, "reason") else "Ok"}')
                else:
                    self.message_user(request, f'Unable to start charging at {evse.location}.',
                                      level=messages.ERROR)
            except exceptions.APIException as e:
                self.message_user(request, f'Unable to start charging at {evse.location}. {e}',
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
    list_display = [
        'party',
        'start_date_time',  # Todo: Show time in local timezone
        'total_session_time', 'total_energy', 'total_cost',
    ]
    fieldsets = (
        ('Identification', dict(fields=(('country_code', 'party_id', 'uid'),
                                        ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id')))),
        ('Location', dict(fields=(('cdr_location_name', 'cdr_location_city', 'cdr_location_country'),
                                  ('cdr_location_evse_uid', 'cdr_location_connector_id'),))),
        ('Delivery', dict(fields=(('total_energy', 'total_time', 'auth_method'), ('total_cost_incl_vat', 'total_cost_excl_vat', 'currency'),))),
        ('Time period', dict(fields=(('start_date_time', 'end_date_time'), 'last_updated'))),
        ('Credited or not', dict(fields=(('credit', 'credit_reference'),))),
    )
    # list_filter = ['party_id', 'auth_method', 'credit']
    list_display_links = ['start_date_time']
    search_fields = ['party_id', 'country_code', 'session_id', 'uid']
    autocomplete_fields = ['tariffs']

    def has_delete_permission(self, request, obj=None) -> bool:
        # Disable delete
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request) -> bool:
        # Disable add
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_change_permission(self, request, obj=None) -> bool:
        # Disable change
        return ALLOW_ADMIN_DELETE_AND_CHANGE


class SessionAdmin(admin.ModelAdmin):
    model = Session
    ordering = ['-created']
    list_display = [
        'party',
        'start_date_time',  # Todo: Show time in local timezone
        'status',
        'evse', 'connector',
        'cdr_token_uid',
        'total_time', 'kwh', 'cost'
    ]
    fieldsets = (
        ('Identification', dict(fields=(('country_code', 'party_id'), ('uid', 'meter_id'),
                                        ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id')))),
        ('Delivery', dict(fields=(('status', 'kwh'), ('total_cost_incl_vat', 'total_cost_excl_vat', 'currency'),
                                  'auth_method',))),
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
                     'uid']
    # list_filter = ['status', 'party_id',]
    readonly_fields = ['uid', 'party_id', 'country_code']

    # def formfield_for_foreignkey(self, db_field, request, **kwargs):
    #     if db_field.name == "connector":
    #         kwargs["queryset"] = Connector.objects.filter(evse=??)
    #     return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return [
                'country_code', 'party_id', 'meter_id',
                'authorization_reference', 'uid', 'auth_method',
                'cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id',
                'location', 'evse', 'start_date_time', 'total_cost_incl_vat', 'total_cost_excl_vat',
            ]
        return []

    def has_delete_permission(self, request, obj=None) -> bool:
        # Disable delete except for invalid sessions
        return (obj and obj.status == 'INVALID') or ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_change_permission(self, request, obj: Session = None) -> bool:
        if obj and obj.status == Session.COMPLETED and obj.total_cost_excl_vat:
            return False
        return (obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID) \
               or ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request) -> bool:
        # Disable add
        return False

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

            # This is also not working, PriceComponents are always editable
            # def has_change_permission(self, request, obj=None):
            #     if isinstance(obj, TariffElement) and obj.tariff:
            #         obj = obj.tariff
            #     return (obj and not obj.archived and
            #         obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID) \
            #         or ALLOW_ADMIN_DELETE_AND_CHANGE

        model = TariffElement
        inlines = [PriceComponentsInline]

    model = Tariff
    list_display = [
        # 'archived',
        'party', 'uid', 'price', 'references'
    ]
    list_display_links = ['uid']
    inlines = [ElementsInline]
    search_fields = ['uid']
    # list_filter = ['archived']
    radio_fields = dict(type=admin.HORIZONTAL)
    exclude = ['archived', 'last_updated']

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
        return (obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID) \
               or ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_delete_permission(self, request, obj=None) -> bool:
        return ALLOW_ADMIN_DELETE_AND_CHANGE or self.has_change_permission(request, obj)


class CredentialsAdmin(admin.ModelAdmin):
    class CredentialRolesInline(admin.TabularInline):
        model = CredentialsRole.credentials.through

    class EndpointsInline(admin.TabularInline):
        model = Endpoint

    model = Credentials
    list_display = ['party', 'token_a_base64', 'ours_base64', 'theirs_base64']
    readonly_fields = ['ours', 'theirs_base64', 'last_updated', 'created']
    inlines = [CredentialRolesInline, EndpointsInline]
    search_fields = ['roles__party_id', 'roles__country_code']
    list_display_links = ['token_a_base64']


@admin.register(CredentialsRole)
class CredentialsRoleAdmin(admin.ModelAdmin):
    model = CredentialsRole
    list_display = ['party', 'business_details', 'references']


@admin.register(DefaultTariffs)
class DefaultTariffsAdmin(admin.ModelAdmin):
    model = DefaultTariffs
    list_display = ['standard', 'tariff_list']
    autocomplete_fields = ['tariffs']


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
