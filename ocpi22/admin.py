from django.conf import settings
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from nested_admin.nested import NestedModelAdmin, NestedStackedInline, NestedTabularInline
from requests import Response
from rest_framework import exceptions

from ocpi22.commands import send_start_command
from ocpi22.models import Token, Location, BusinessDetails, Facility, Evse, Connector, Capability, Tariff, \
    PriceComponent, Cdr, Session, Credentials, CredentialsRole, Endpoint, TariffElement
from ocpi22.tokens import get_admin_token

ALLOW_ADMIN_DELETE_AND_CHANGE = False


class TokenAdmin(admin.ModelAdmin):
    model = Token
    search_fields = ['party_id', 'uid', 'contract_id', 'visual_number', 'issuer', 'default_profile_type', 'type']
    list_display = ['party', 'valid', 'uid', 'type', 'visual_number', 'contract_id', 'last_updated']
    list_filter = ['party_id', 'country_code', 'type', 'group_id', 'contract_id']
    list_display_links = ['uid']
    readonly_fields = ['country_code', 'party_id']

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    # def has_add_permission(self, request, obj=None):
    #     # Disable add
    #     return False

    def has_change_permission(self, request, obj: Token = None):
        return obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID


# from django import forms


# class LocationForm(forms.ModelForm):
#     def validate_unique(self):
#         super().validate_unique()
#         ic(self.data)
#         latitude = self.data.get('latitude', '')
#         if "," in latitude:
#             try:
#                 lat, long, *_the_rest = latitude.split(",")
#                 self.data['latitude'] = lat
#                 self.data['longitude'] = long
#                 self.cleaned_data['latitude'] = lat
#                 self.cleaned_data['longitude'] = long
#             except:
#                 pass
#
#     latitude = forms.CharField()

class LocationAdmin(admin.ModelAdmin):
    class EvseInline(admin.TabularInline):
        model = Evse

    # form = LocationForm
    model = Location
    search_fields = ['country_code', 'party_id', 'uid', 'name', 'address', 'city',
                     'postal_code', 'state', 'country', 'parking_type']
    fields = ['uid', 'publish', 'publish_allowed_to',
              ('name', 'address'), ('postal_code', 'city'), ('state', 'country'), ('latitude', 'longitude'),
              ('parking_type', 'facilities'), ('operator', 'suboperator', 'owner'), 'time_zone']
    list_display = ['party', 'uid', 'publish', 'name', 'street_address', 'evse_list']
    list_display_links = ['uid']

    def has_change_permission(self, request, obj=None):
        return obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID

    def has_delete_permission(self, request, obj=None):
        return ALLOW_ADMIN_DELETE_AND_CHANGE


class EvseAdmin(admin.ModelAdmin):
    class ConnectorInline(admin.TabularInline):
        model = Connector

    model = Evse
    list_display = ['party', 'evse_id', 'location_url', 'status', 'connector_list']
    inlines = [ConnectorInline]
    search_fields = ['evse_id', 'location__address', 'location__city', 'location__name']
    actions = ['start_charging']
    # raw_id_fields = ['location']

    @staticmethod
    def location_url(evse):
        return format_html("<a href='{url}'>{location}</a>",
                           url=reverse('admin:ocpi22_location_change', args=[evse.location.pk]),
                           location=str(evse.location))

    def has_change_permission(self, request, obj=None):
        return obj and obj.location.country_code == settings.COUNTRY_CODE and obj.location.party_id == settings.PARTY_ID

    def has_delete_permission(self, request, obj=None):
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
                                               f'{response.reason if hasattr(response, "reason") else "Ok" }')
                else:
                    self.message_user(request, f'Unable to start charging at {evse.location}.',
                                      level=messages.ERROR)
            except exceptions.APIException as e:
                self.message_user(request, f'Unable to start charging at {evse.location}. {e}',
                                  level=messages.ERROR)


class BusinessDetailsAdmin(admin.ModelAdmin):
    model = BusinessDetails
    list_display = ['name', 'website', 'logo', 'referenced_locations', 'referenced_credentials']


class FacilityAdmin(admin.ModelAdmin):
    model = Facility
    list_display = ['name', 'description']

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return False

    def has_add_permission(self, request):
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

    def has_add_permission(self, request):
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
    # list_filter = ['party_id', 'auth_method', 'credit']
    list_display_links = ['start_date_time']
    search_fields = ['party_id', 'country_code', 'session_id']

    def has_delete_permission(self, request, obj=None):
        # Disable delete
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request):
        # Disable add
        return ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_change_permission(self, request, obj=None):
        # Disable change
        return ALLOW_ADMIN_DELETE_AND_CHANGE


class SessionAdmin(admin.ModelAdmin):
    model = Session
    ordering = ['-created']
    list_display = [
        'party',
        'start_date_time',  # Todo: Show time in local timezone
        'status',
        'total_time',
        'evse', 'connector',
        'cdr_token_uid', 'kwh',
        'cost'
    ]
    # fields = (
    #     ('start_date_time', 'end_date_time'),
    #     ('cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id'),
    #     ('status', 'kwh'),
    #     ('total_cost_excl_vat', 'total_cost_incl_vat', 'currency')
    # )
    list_display_links = ['start_date_time']
    search_fields = ['location__name', 'location__address', 'evse__evse_id', 'evse__uid', 'party_id', 'cdr_token_uid', 'uid']
    # list_filter = ['status', 'party_id',]
    readonly_fields = ['uid', 'party_id', 'country_code']

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (
                'country_code', 'party_id', 'meter_id',
                'authorization_reference', 'uid', 'auth_method',
                'cdr_token_uid', 'cdr_token_type', 'cdr_token_contract_id',
                'location', 'evse', 'connector', 'start_date_time'
            )
        return []

    def has_delete_permission(self, request, obj=None):
        # Disable delete except for invalid sessions
        return (obj and obj.status == 'INVALID') or ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_add_permission(self, request):
        # Disable add
        return ALLOW_ADMIN_DELETE_AND_CHANGE


class TariffAdmin(NestedModelAdmin):

    class ElementsInline(NestedStackedInline):
        class PriceComponentsInline(NestedTabularInline):
            model = PriceComponent
        model = TariffElement
        inlines = [PriceComponentsInline]

    model = Tariff
    list_display = ['party', 'uid', 'price', 'last_updated']
    list_display_links = ['uid']
    inlines = [ElementsInline]
    readonly_fields = ['country_code', 'party_id']

    def has_change_permission(self, request, obj=None):
        return (obj and obj.country_code == settings.COUNTRY_CODE and obj.party_id == settings.PARTY_ID) \
            or ALLOW_ADMIN_DELETE_AND_CHANGE

    def has_delete_permission(self, request, obj=None):
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
