from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from ocpi22.models import Token, Location, BusinessDetails, Facility, Evse, Connector, Capability, Tariff, \
    PriceComponent


class TokenAdmin(admin.ModelAdmin):
    model = Token
    search_fields = ['party_id', 'uid', 'contract_id', 'visual_number', 'issuer', 'default_profile_type', 'type']


class EvseInline(admin.TabularInline):
    model = Evse


class ConnectorInline(admin.TabularInline):
    model = Connector


class LocationAdmin(admin.ModelAdmin):
    model = Location
    search_fields = ['party_id', 'uid', 'name', 'address', 'city', 'postal_code', 'state', 'country', 'parking_type']
    list_display = ['publish', 'name', 'address', 'city', 'country', 'party_id', 'country_code', 'actions_item']
    list_display_links = ['actions_item']
    # inlines = [EvseInline]

    def actions_item(self, _obj):
        return format_html('Edit')

    actions_item.short_description = ''


class EvseAdmin(admin.ModelAdmin):
    model = Evse
    list_display = ['evse_id', 'location_url', 'status', 'connector_list']
    inlines = [ConnectorInline]

    def location_url(self, evse):
        return format_html("<a href='{url}'>{location}</a>",
                           url=reverse('admin:ocpi22_location_change', args=[evse.location.pk]),
                           location=str(evse.location))

    location_url.short_description = "Location"


# class ConnectorAdmin(admin.ModelAdmin):
#     model = Connector
#     list_display = ['location_url', 'evse_url', 'standard', 'format', 'power_type', 'power', 'tariff']
#
#     def evse_url(self, connector):
#         return format_html("<a href='{url}'>{evse}</a>",
#                            url=reverse('admin:ocpi22_evse_change', args=[connector.evse.pk]),
#                            evse=str(connector.evse))
#
#     evse_url.short_description = "Evse"
#
#     def location_url(self, connector):
#         return format_html("<a href='{url}'>{location}</a>",
#                            url=reverse('admin:ocpi22_location_change', args=[connector.evse.location.pk]),
#                            location=str(connector.evse.location))
#
#     location_url.short_description = "Location"


class BusinessDetailsAdmin(admin.ModelAdmin):
    model = BusinessDetails
    list_display = ['name', 'website', 'logo']
    list_editable = ['website', 'logo']


class FacilityAdmin(admin.ModelAdmin):
    model = Facility
    list_display = ['name', 'description']


class CapabilityAdmin(admin.ModelAdmin):
    model = Capability
    list_display = ['name', 'description']


class PriceComponentsInline(admin.TabularInline):
    model = PriceComponent


class TariffAdmin(admin.ModelAdmin):
    model = Tariff
    list_display = ['party_id', '__str__', 'type', 'tariff_alt_url', 'country_code']
    list_display_links = ['__str__']
    inlines = [ PriceComponentsInline ]


admin.site.register(Token, TokenAdmin)
admin.site.register(Location, LocationAdmin)
admin.site.register(Evse, EvseAdmin)
# admin.site.register(Connector, ConnectorAdmin)
admin.site.register(BusinessDetails, BusinessDetailsAdmin)
admin.site.register(Facility, FacilityAdmin)
admin.site.register(Capability, CapabilityAdmin)
admin.site.register(Tariff, TariffAdmin)
# admin.site.register(PriceComponent, PriceComponentAdmin)
