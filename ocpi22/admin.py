from django.contrib import admin

from ocpi22.models import Token, Location, BusinessDetails, Facility, Evse, Connector, Capability, Tariff, \
    PriceComponent


class TokenAdmin(admin.ModelAdmin):
    model = Token


class LocationAdmin(admin.ModelAdmin):
    model = Location


class EvseAdmin(admin.ModelAdmin):
    model = Evse


class ConnectorAdmin(admin.ModelAdmin):
    model = Connector


class BusinessDetailsAdmin(admin.ModelAdmin):
    model = BusinessDetails


class FacilityAdmin(admin.ModelAdmin):
    model = Facility


class CapabilityAdmin(admin.ModelAdmin):
    model = Capability


class PriceComponentsInline(admin.TabularInline):
    model = PriceComponent


class PriceComponentAdmin(admin.ModelAdmin):
    model = PriceComponent


class TariffAdmin(admin.ModelAdmin):
    model = Tariff
    inlines = [ PriceComponentsInline ]


admin.site.register(Token, TokenAdmin)
admin.site.register(Location, LocationAdmin)
admin.site.register(Evse, EvseAdmin)
admin.site.register(Connector, ConnectorAdmin)
admin.site.register(BusinessDetails, BusinessDetailsAdmin)
admin.site.register(Facility, FacilityAdmin)
admin.site.register(Capability, CapabilityAdmin)
admin.site.register(Tariff, TariffAdmin)
admin.site.register(PriceComponent, PriceComponentAdmin)
