from django.conf import settings
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from ocpi22.models import Token, Location, BusinessDetails, Facility, Evse, Connector, Capability, Tariff, \
    PriceComponent, Cdr, Session, Credentials, CredentialsRole, Endpoint


class TokenAdmin(admin.ModelAdmin):
    model = Token
    search_fields = ['party_id', 'uid', 'contract_id', 'visual_number', 'issuer', 'default_profile_type', 'type']
    list_display = ['party', 'valid', 'type', 'uid', 'visual_number', 'contract_id', 'last_updated']
    list_filter = ['party_id', 'country_code', 'type', 'group_id', 'contract_id']
    list_display_links = ['uid']
    # exclude = ['country_code', 'party_id']

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    # def has_add_permission(self, request, obj=None):
    #     # Disable add
    #     return False

    def has_change_permission(self, request, token: Token=None):
        return token and token.country_code == settings.COUNTRY_CODE and token.party_id == settings.PARTY_ID


class LocationAdmin(admin.ModelAdmin):
    class EvseInline(admin.TabularInline):
        model = Evse

    model = Location
    search_fields = ['country_code', 'party_id', 'uid', 'name', 'address', 'city',
                     'postal_code', 'state', 'country', 'parking_type']
    fields = ['uid', 'publish', 'publish_allowed_to',
              ('name', 'address'), ('postal_code', 'city'), ('state', 'country'), ('latitude', 'longitude'),
              ('parking_type', 'facilities'), ('operator', 'suboperator', 'owner'), 'time_zone',]
    list_display = ['party', 'uid', 'publish', 'name', 'street_address']
    list_display_links = ['uid']

    def has_change_permission(self, request, obj=None):
        return obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID

    def actions_item(self, _obj):
        return format_html('Edit')

    actions_item.short_description = ''


class EvseAdmin(admin.ModelAdmin):
    class ConnectorInline(admin.TabularInline):
        model = Connector

    model = Evse
    list_display = ['evse_id', 'location_url', 'status', 'connector_list']
    inlines = [ConnectorInline]
    search_fields = ['evse_id', 'location__address', 'location__city', 'location__name']

    def location_url(self, evse):
        return format_html("<a href='{url}'>{location}</a>",
                           url=reverse('admin:ocpi22_location_change', args=[evse.location.pk]),
                           location=str(evse.location))

    def has_change_permission(self, request, obj=None):
        return obj and obj.location.country_code == settings.COUNTRY_CODE and obj.location.party_id == settings.PARTY_ID

    location_url.short_description = "Location"


class BusinessDetailsAdmin(admin.ModelAdmin):
    model = BusinessDetails
    list_display = ['name', 'website', 'logo', 'referenced_locations', 'referenced_credentials']


class FacilityAdmin(admin.ModelAdmin):
    model = Facility
    list_display = ['name', 'description']

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def has_add_permission(self, request, obj=None):
        # Disable add
        return False

    def has_change_permission(self, request, obj=None):
        # Disable change
        return False


class CapabilityAdmin(admin.ModelAdmin):
    model = Capability
    list_display = ['name', 'description']

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def has_add_permission(self, request, obj=None):
        # Disable add
        return False

    def has_change_permission(self, request, obj=None):
        # Disable change
        return False


class CdrAdmin(admin.ModelAdmin):
    model = Cdr
    list_display = [
        'party',
        'start_date_time',  # Todo: Show time in local timezone
        'total_cost', 'total_energy', 'charging_time',
        'session_id', 'auth_method'
    ]
    list_filter = ['party_id', 'auth_method', 'credit']
    list_display_links = ['start_date_time']
    search_fields = ['party_id', 'country_code', 'session_id']

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def has_add_permission(self, request, obj=None):
        # Disable add
        return False

    def has_change_permission(self, request, obj=None):
        # Disable change
        return False


class SessionAdmin(admin.ModelAdmin):
    model = Session
    ordering = ['-created']
    list_display = [
        'party',
        'start_date_time',  # Todo: Show time in local timezone
        'status',
        'total_time',
        'location', 'evse', 'connector',
        'cdr_token_uid', 'kwh', 'last_updated',
        'total_cost_incl_vat', 'total_cost_excl_vat', 'currency'
    ]
    list_display_links = ['start_date_time']
    search_fields = ['location__name', 'location__address', 'evse__uid', 'party_id', 'cdr_token_uid']
    list_filter = ['status']
    readonly_fields = ['uid', 'party_id', 'country_code']

    def has_delete_permission(self, request, obj=None):
        # Disable delete except for invalid sessions
        return obj and obj.status == 'INVALID'

    def has_add_permission(self, request, obj=None):
        # Disable add
        return False


class TariffAdmin(admin.ModelAdmin):

    class PriceComponentsInline(admin.TabularInline):
        model = PriceComponent

    model = Tariff
    list_display = ['party', 'uid', 'price', 'last_updated',
                    'country_code', 'party_id',
                    ]
    list_display_links = ['price']
    inlines = [PriceComponentsInline]
    readonly_fields = ['last_updated']

    def has_change_permission(self, request, obj=None):
        return obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


class CredentialsAdmin(admin.ModelAdmin):

    class CredentialRolesInline(admin.TabularInline):
        model = CredentialsRole.credentials.through

    class EndpointsInline(admin.TabularInline):
        model = Endpoint

    model = Credentials
    list_display = ['party', 'token_a_base64', 'ours_base64', 'theirs_base64']
    readonly_fields = ['ours', 'theirs_base64', 'last_updated', 'created']
    inlines = [CredentialRolesInline, EndpointsInline]
    search_fields = ['roles__party_id', 'roles__country_code',]
    list_display_links = ['token_a_base64']


@admin.register(CredentialsRole)
class CredentialsRoleAdmin(admin.ModelAdmin):
    model = CredentialsRole
    list_display = ['operator', 'business_details', 'references']


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
