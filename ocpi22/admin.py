import pytz
from django.utils.datetime_safe import datetime
from django.utils.translation import gettext_lazy as _

from django import forms
from django.core.exceptions import ValidationError
from gdpr_assist.admin import PersonalDataAdmin, PersonalData

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.models import User

import widgets
from ocpi22.choices import OcpiRolesEnum, OCPIFacility, OCPICapability
from django.utils.html import format_html
from nested_admin.nested import (
    NestedModelAdmin,
    NestedStackedInline,
    NestedTabularInline,
)

from ocpi22.models.cdr import Cdr
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.credentials import Credentials, CredentialsRole, Endpoint
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session, ChargingPeriod, CdrDimension
from ocpi22.models.tariff import PriceComponent, TariffElement, Tariff, DefaultTariffs
from ocpi22.models.token import Token
from ocpi22.msp.account import Account, Transaction
from ocpi22.msp.models import Authorization
from ocpi22.ocpi.partners import (
    invalidate_partner_cache,
    get_partners_by_party_as_party,
)
from ocpi22.pull import admin_pull_all
from ocpiconnector.ocpi_identities import (
    ocpi_identities,
    ocpi_platform,
    get_our_credentialsrole,
)
from ocpiconnector.party import Party
from payment.models import Payment

admin.site.site_header = "Roaming Admin"
admin.site.index_title = "Dashboard"


class AdminUtilityMixin:
    def last_update(self, obj):
        return obj.last_updated

    last_update.admin_order_field = "last_updated"
    last_update.short_description = "Last update"


class SolidModelAdmin(admin.ModelAdmin, AdminUtilityMixin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if hasattr(obj, "post_process_after_update_or_create"):
            obj.post_process_after_update_or_create()


class SolidNestedModelAdmin(NestedModelAdmin, AdminUtilityMixin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.post_process_after_update_or_create()


class TokenAdmin(SolidModelAdmin):
    model = Token
    search_fields = [
        "ocpi_master__country_code",
        "ocpi_master__party_id",
        "uid",
        "contract_id",
        "visual_number",
        "issuer",
        "default_profile_type",
        "type",
        "customer__username",
        "customer__first_name",
        "customer__last_name",
    ]
    if ocpi_platform.is_emsp:
        list_display = [
            "valid",
            "party_long",
            "customer_name",
            "uid",
            "type",
            "visual_number",
            "balances",
            "last_update",
        ]
    else:
        list_display = [
            "valid",
            "party_long",
            "uid",
            "type",
            "visual_number",
            "last_update",
        ]
    list_display_links = ["uid"]
    readonly_fields = ["ocpi_master", "last_updated", "created", "type"]

    def customer_name(self, obj) -> str:
        if not obj.customer:
            return "N/A"
        from util import reverse

        return format_html(
            f'<a href="{reverse("admin:auth_user_change", args=[obj.customer.pk])}">'
            f'{obj.customer.first_name} {obj.customer.last_name}</a>'
        )

    fieldsets = [
        ("Customer", dict(fields=(("customer",)))),
        (
            "Identification",
            dict(
                fields=(
                    "ocpi_master",
                    ("uid", "visual_number"),
                    ("issuer", "group_id"),
                    "contract_id",
                )
            ),
        ),
        (
            "Specifics",
            dict(
                fields=(
                    ("valid", "type", "whitelist"),
                    ("language", "default_profile_type"),
                )
            ),
        ),
        ("Dates", dict(fields=(("created", "last_updated")))),
    ]

    def has_add_permission(self, request) -> bool:
        return (
            Token.ocpi_object_owner in ocpi_identities
            or settings.ALLOW_ADMIN_DELETE_AND_CHANGE
        ) and super().has_add_permission(request)

    def has_change_permission(self, request, obj: Token = None) -> bool:
        return (
            (obj and obj.is_ours()) or settings.ALLOW_ADMIN_DELETE_AND_CHANGE
        ) and super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
        our_msp_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.EMSP)
        try:
            if (
                not settings.ALLOW_ADMIN_DELETE_AND_CHANGE
                and obj.ocpi_master
                and obj.ocpi_master != our_msp_credentialsrole
            ):
                raise ValidationError("This is not our object")
        except Location.ocpi_master.RelatedObjectDoesNotExist:
            pass
        obj.ocpi_master = our_msp_credentialsrole
        if hasattr(obj, "update_last_updated"):
            obj.update_last_updated()
        super().save_model(request, obj, form, change)


# Todo: Prevent Connector editing if not owner, get_readonly_fields() doesn't do it


class ConnectorAdminForm(forms.ModelForm):
    def clean_tariff_ids(self):
        data = self.cleaned_data.get("tariff_ids")
        if not data:
            raise ValidationError(
                _(
                    "Connector needs to have a Tariff selected, so that billing is possible"
                ),
                code="invalid",
            )
        return data


class ConnectorInline(NestedStackedInline):
    model = Connector
    form = ConnectorAdminForm

    fieldsets = [
        (
            None,
            dict(
                fields=[
                    ("uid", "standard"),
                    ("format", "power_type"),
                    ("max_voltage", "max_amperage"),
                    ("tariff_ids",),
                    ("terms_and_conditions",),
                ]
            ),
        ),
    ]
    radio_fields = dict(format=admin.VERTICAL, power_type=admin.VERTICAL)
    autocomplete_fields = ["tariff_ids"]

    formfield_overrides = widgets.formfield_overrides

    def has_change_permission(self, request, obj: Evse = None) -> bool:
        # Todo: Admin should only be able to change owned Connectors
        if obj and hasattr(obj, "location"):
            obj = obj.location
        return (
            obj
            and hasattr(obj, "is_ours")
            and obj.is_ours()
            and super().has_change_permission(request, obj)
        )

    def has_add_permission(self, request, obj=None) -> bool:
        return (
            Location.ocpi_object_owner in ocpi_identities
            and super().has_add_permission(request, obj)
        )


class LocationAdminForm(forms.ModelForm):
    facilities = forms.MultipleChoiceField(
        choices=OCPIFacility.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = Location
        fields = "__all__"


class EvseAdminForm(forms.ModelForm):
    capabilities = forms.MultipleChoiceField(
        choices=OCPICapability.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = Evse
        fields = "__all__"


@admin.action(description="Send background updates to interested parties")
def send_updates(modeladmin, request, queryset):
    model_cls = queryset.model
    if not hasattr(model_cls, "send_updates"):
        modeladmin.message_user(
            request,
            f"{model_cls.__name__} does not have a send_updates method.",
            level=messages.ERROR,
        )
        return
    count = queryset.count()
    MAX_OBJECTS = 100
    WARN_OBJECTS = 50
    if count > MAX_OBJECTS:
        modeladmin.message_user(
            request,
            f"Cannot send updates to more than {MAX_OBJECTS} {model_cls.__name__}s at once. Please select fewer {model_cls.__name__}s.",
            level=messages.ERROR,
        )
        return
    elif count > WARN_OBJECTS:
        modeladmin.message_user(
            request,
            f"Warning: Sending updates to {count} {model_cls.__name__}s may take some time.",
            level=messages.WARNING,
        )
    for obj in queryset:
        obj.send_updates()
    modeladmin.message_user(
        request,
        f"Updates sent for {count} {model_cls.__name__}s.",
        level=messages.SUCCESS,
    )


class LocationAdmin(SolidNestedModelAdmin):
    class EvseInline(NestedStackedInline):
        model = Evse
        form = EvseAdminForm
        exclude = ["evse_id", "last_updated"]
        inlines = [ConnectorInline]

        formfield_overrides = widgets.formfield_overrides

        def has_change_permission(self, request, obj=None) -> bool:
            return obj and obj.is_ours() and super().has_change_permission(request, obj)

        def has_add_permission(self, request, obj=None) -> bool:
            return (
                Location.ocpi_object_owner in ocpi_identities
                and super().has_add_permission(request, obj)
            )

    # The below doesn't work, need more time to work on it
    #
    # class OpeningTimesInline(NestedTabularInline):
    #     class RegularHoursInline(NestedTabularInline):
    #         model = RegularHours
    #         fields = ['weekday', 'period_begin', 'period_end']
    #
    #     model = Hours
    #
    #     fields = ['twentyfourseven', 'regular_hours', 'exceptional_openings', 'exceptional_closings']
    #
    #     formfield_overrides = widgets.formfield_overrides
    #     inlines = [RegularHoursInline]
    #
    #     def has_change_permission(self, request, obj=None) -> bool:
    #         return obj and obj.is_ours() and super().has_change_permission(request, obj)
    #
    #     def has_add_permission(self, request, obj=None) -> bool:
    #         return Location.ocpi_object_owner in ocpi_identities and super().has_add_permission(request, obj)

    formfield_overrides = widgets.formfield_overrides

    model = Location
    form = LocationAdminForm
    search_fields = [
        "ocpi_master__country_code",
        "ocpi_master__party_id",
        "uid",
        "name",
        "address",
        "city",
        "postal_code",
        "state",
        "country",
        "parking_type",
    ]
    fieldsets = [
        (
            "Address",
            dict(
                fields=(
                    "uid",
                    "name",
                    "address",
                    ("postal_code", "city"),
                    ("state", "country"),
                    ("latitude", "longitude", "time_zone"),
                    "publish",
                    "roaming_enabled",
                )
            ),
        ),
        ("Features", dict(fields=(("parking_type", "facilities"),))),
        ("Parties", dict(fields=(("operator", "suboperator", "owner"),))),
    ]
    list_display = [
        "party_long",
        "uid",
        "publish",
        "roaming_enabled",
        "name",
        "street_address",
        "evse_list",
    ]
    list_display_links = ["uid"]
    inlines = [EvseInline]  # [OpeningTimesInline, EvseInline]
    autocomplete_fields = ["publish_allowed_to", "operator", "suboperator", "owner"]
    radio_fields = dict(parking_type=admin.VERTICAL)
    actions = [send_updates]

    def has_change_permission(self, request, obj=None) -> bool:
        return obj and obj.is_ours() and super().has_change_permission(request, obj)

    def has_add_permission(self, request) -> bool:
        return (
            Location.ocpi_object_owner in ocpi_identities
            and super().has_add_permission(request)
        )

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ["uid"]
        return []

    def save_model(self, request, obj, form, change):
        """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
        our_cpo_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.CPO)
        try:
            if (
                not settings.ALLOW_ADMIN_DELETE_AND_CHANGE
                and obj.ocpi_master
                and obj.ocpi_master != our_cpo_credentialsrole
            ):
                raise ValidationError("This is not our object")
        except Location.ocpi_master.RelatedObjectDoesNotExist:
            pass
        obj.ocpi_master = our_cpo_credentialsrole
        if hasattr(obj, "update_last_updated"):
            obj.update_last_updated()

        super().save_model(request, obj, form, change)


class EvseAdminForm(forms.ModelForm):
    def clean_uid(self):
        # if Evse.objects.filter(uid=self.data['uid']).count():
        #     # Todo: Recognize if it's the same object, and allow it
        #     raise ValidationError(_('EVSE with this UID already exists in this or another Location'),)
        return self.cleaned_data["uid"]


class EvseAdmin(SolidNestedModelAdmin):
    form = EvseAdminForm
    model = Evse
    # Todo: In API, return most recent of last_updated and updated, but only owner can PATCH last_updated
    list_display = [
        "party_long",
        "uid",
        "location_link",
        "status",
        "connector_list",
        "last_update",
    ]
    list_display_links = ["uid"]
    inlines = [ConnectorInline]
    search_fields = [
        "evse_id",
        "location__address",
        "location__city",
        "location__name",
        "location__uid",
    ]
    # actions = ['start_charging', 'stop_charging']
    autocomplete_fields = ["location"]
    exclude = ["last_updated"]
    list_filter = ["status"]

    formfield_overrides = widgets.formfield_overrides

    def get_queryset(self, request):
        return Evse.objects.select_related("location").all().order_by("-last_updated")

    @staticmethod
    def location_link(evse):
        from util import reverse

        return format_html(
            "<a href='{url}'>{location}</a>",
            url=reverse("admin:ocpi22_location_change", args=[evse.location.pk]),
            location=str(evse.location),
        )

    location_link.short_description = "Location"

    def last_update(self, obj):
        return obj.last_updated

    last_update.admin_order_field = "last_updated"
    last_update.short_description = "Last update"

    def get_readonly_fields(self, request, obj=None) -> list:
        if obj:
            return ["last_updated"]
        return []

    def has_change_permission(self, request, obj=None) -> bool:
        return (
            not obj
            or (hasattr(obj, "location") and obj.location.is_ours())
            and super().has_change_permission(request, obj)
        )

    # def save_model(self, request, obj, form, change):
    #     """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
    #     our_cpo_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.CPO)
    #     if not settings.ALLOW_ADMIN_DELETE_AND_CHANGE and obj.ocpi_master and obj.ocpi_master != our_cpo_credentialsrole:
    #         raise ValidationError('This is not our object')
    #     obj.ocpi_master = our_cpo_credentialsrole
    #     obj.last_updated = datetime.utcnow
    #     super().save_model(request, obj, form, change)


@admin.register(BusinessDetails)
class BusinessDetailsAdmin(SolidModelAdmin):
    model = BusinessDetails
    list_display = [
        "name",
        "website",
        "logo",
        "referenced_locations",
        "referenced_credentials",
    ]
    search_fields = ["name", "website"]


class CdrAdmin(SolidModelAdmin):
    model = Cdr
    ordering = ("-start_date_time",)
    if ocpi_platform.is_cpo:
        list_display = [
            "start_date_time",  # Todo: Show time everywhere in local timezone
            "billed_to",
            "evse_id",
            "total_session_time",
            "total_energy",
            "total_cost",
        ]
    else:
        list_display = [
            "party_long",
            "start_date_time",  # Todo: Show time everywhere in local timezone
            "evse_id",
            "total_session_time",
            "total_energy",
            "total_cost",
        ]
    fieldsets = (
        (
            "Identification",
            dict(
                fields=(
                    ("ocpi_master", "uid"),
                    ("cdr_token",),
                )
            ),
        ),
        (
            "Location",
            dict(fields=(("cdr_location",),)),
        ),
        (
            "Delivery",
            dict(
                fields=(
                    ("total_energy", "auth_method"),
                    ("total_cost_incl_vat", "total_cost_excl_vat", "currency"),
                )
            ),
        ),
        ("Time period", dict(fields=(("start_date_time", "end_date_time"),))),
        ("Credited or not", dict(fields=(("credit", "credit_reference"),))),
    )
    list_display_links = ["start_date_time"]
    search_fields = [
        "session_id",
        "uid",
        "cdr_location__evse_id",
        "cdr_location__name",
        "cdr_location__city",
        "cdr_location__country",
        "cdr_token__uid",
        "cdr_token__contract_id",
        "billed_to",
    ]
    autocomplete_fields = ["tariffs"]

    formfield_overrides = widgets.formfield_overrides

    def has_add_permission(self, request) -> bool:
        # Disable add
        return settings.ALLOW_ADMIN_DELETE_AND_CHANGE and super().has_add_permission(
            request
        )

    def has_change_permission(self, request, obj=None) -> bool:
        # Disable change
        return settings.ALLOW_ADMIN_DELETE_AND_CHANGE and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None) -> bool:
        # Disable delete
        return settings.ALLOW_ADMIN_DELETE_AND_CHANGE and super().has_delete_permission(
            request, obj
        )


class SessionAdmin(SolidNestedModelAdmin):
    class ChargingPeriodInline(NestedStackedInline):
        model = ChargingPeriod

        class CdrDimensionInline(NestedTabularInline):
            model = CdrDimension

        inlines = [CdrDimensionInline]

    model = Session
    ordering = ["-updated"]
    list_display = [
        "uid",
        "location",
        "party_long",
        "kwh",
        "cost",
        "last_update",
        "status",
    ]

    list_display_links = ["location", "status"]

    formfield_overrides = widgets.formfield_overrides

    inlines = [ChargingPeriodInline]
    fieldsets = (
        (
            "Identification",
            dict(
                fields=(
                    ("ocpi_master",),
                    ("uid", "meter_id"),
                    ("cdr_token",),
                    ("location", "evse", "connector"),
                )
            ),
        ),
        (
            "Delivery",
            dict(
                fields=(
                    ("status", "start_kwh", "stop_kwh"),
                    ("total_cost_incl_vat", "total_cost_excl_vat", "currency"),
                    ("message",),
                    ("auth_method", "authorization_reference"),
                )
            ),
        ),
        ("Time period", dict(fields=(("start_date_time", "end_date_time"),))),
    )
    # Todo: Show only connectors for the selected evse

    search_fields = [
        "location__name",
        "location__address",
        "evse__evse_id",
        "evse__uid",
        "cdr_token__uid",
        "cdr_token__contract_id",
        "uid",
        "authorization_reference",
    ]
    readonly_fields = [
        "uid",
        "ocpi_master",
        "cdr_token",
        "location",
        "evse",
        "connector",
    ]
    list_filter = ["status", "last_updated"]

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def response_post_save_change(self, request, obj: Session):
        if obj.kwh:
            if obj.calculate_price():
                obj.save(update_fields=["total_cost_excl_vat", "total_cost_incl_vat"])
            else:
                self.message_user(
                    request,
                    "Cannot calculate cost for the session, because there are no Tariffs "
                    "specified for the Connector. "
                    "Please edit the Session or specify a default tariff.",
                    level=messages.WARNING,
                )

        return super().response_post_save_change(request, obj)


class TariffAdminForm(forms.ModelForm):
    def clean_uid(self):
        uid = self.cleaned_data.get("uid")
        ocpi_master = get_our_credentialsrole(OcpiRolesEnum.CPO)
        tariff: Tariff = Tariff.objects.filter(
            uid__iexact=str(uid), ocpi_master=ocpi_master, archived=False
        )
        if tariff.exists():
            raise ValidationError(
                _("Tariff with this UID already exists"), code="invalid"
            )
        return uid


class TariffAdmin(SolidNestedModelAdmin):
    form = TariffAdminForm

    class ElementsInline(NestedStackedInline):
        class PriceComponentsInline(NestedTabularInline):
            model = PriceComponent
            exclude = ["dynamic_price_source"]

            formfield_overrides = widgets.formfield_overrides

            def has_change_permission(self, request, obj=None) -> bool:
                return False

            def has_add_permission(self, request, obj=None) -> bool:
                return (
                    Tariff.ocpi_object_owner in ocpi_identities
                    or super().has_change_permission(request, obj)
                )

        model = TariffElement
        inlines = [PriceComponentsInline]

        formfield_overrides = widgets.formfield_overrides

        fieldsets = [
            (
                "Scope of the below price components",
                dict(
                    fields=(
                        ("start_date", "end_date"),
                        ("start_time", "end_time"),
                        # ('min_kwh', 'max_kwh'),
                        # ('min_power', 'max_power'),
                        # ('min_current', 'max_current'),
                        ("min_duration", "max_duration"),
                        ("day_of_week",),  # 'reservation'),
                    )
                ),
            ),
        ]

        def has_change_permission(self, request, obj=None) -> bool:
            return False

        def has_add_permission(self, request, obj=None) -> bool:
            return (
                Tariff.ocpi_object_owner in ocpi_identities
                and super().has_add_permission(request, obj)
            )

    model = Tariff
    if ocpi_platform.is_cpo:
        list_display = ["uid", "price", "last_update"]
    else:
        list_display = ["party_long", "uid", "price", "last_update"]
    list_display_links = ["uid"]
    inlines = [ElementsInline]
    search_fields = ["uid"]
    readonly_fields = ("last_updated",)

    formfield_overrides = widgets.formfield_overrides

    fieldsets = [
        (
            "",
            dict(
                fields=(
                    ("ocpi_master",),
                    ("uid",),
                    ("currency",),
                    ("type",),
                    ("tariff_alt_url",),
                )
            ),
        ),
        (
            "Price limits",
            dict(
                fields=(
                    ("min_price_excl_vat", "min_price_incl_vat"),
                    ("max_price_excl_vat", "max_price_incl_vat"),
                )
            ),
        ),
    ]
    actions = [send_updates]

    def get_queryset(self, _request):
        # Hide archived
        return Tariff.objects.exclude(archived=True)

    def get_readonly_fields(self, request, obj=None) -> list:
        readonly_fields = ["ocpi_master"]
        if obj:
            readonly_fields.append("uid")
        return readonly_fields

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_add_permission(self, request) -> bool:
        return (
            Tariff.ocpi_object_owner in ocpi_identities
            and super().has_add_permission(request)
        )

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def save_model(self, request, obj, form, change):
        """Since the admin is saving the object, it's ours, so let's fill out the needed fields"""
        try:
            our_cpo_credentialsrole = get_our_credentialsrole(OcpiRolesEnum.CPO)
            if not change:
                obj.ocpi_master = our_cpo_credentialsrole
            elif (
                not settings.ALLOW_ADMIN_DELETE_AND_CHANGE
                and obj.ocpi_master
                and obj.ocpi_master != our_cpo_credentialsrole
            ):
                raise ValidationError("This is not our object")
        except Location.ocpi_master.RelatedObjectDoesNotExist:
            pass
        obj.last_updated = datetime.now(pytz.utc)
        super().save_model(request, obj, form, change)


class CredentialsAdmin(SolidModelAdmin):
    class CredentialRolesInline(admin.TabularInline):
        model = CredentialsRole

    class EndpointsInline(admin.TabularInline):
        model = Endpoint

    model = Credentials
    list_display = [
        "name",
        "party_str",
        "valid",
        "responding",
        "last_update",
        "allowed_locations",
        "meter_value_frequency",
    ]
    readonly_fields = [
        "theirs_base64",
        "ours_base64",
        "last_updated",
        "created",
        "last_connection",
    ]
    inlines = [CredentialRolesInline, EndpointsInline]
    search_fields = [
        "roles__party_id",
        "roles__country_code",
        "ours",
        "theirs",
        "token_a",
        "roles__business_details__name",
    ]
    list_display_links = ["name"]
    actions = [admin_pull_all]

    def has_add_permission(self, request):
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj=obj)

    def last_update(self, obj):
        return obj.last_connection

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj and change:

            def invalidate_current_partners_cache():
                current_partners: [Party] = list(
                    map(get_partners_by_party_as_party, roles)
                )
                if current_partners:
                    flattened_set = set.union(*current_partners)
                    list(map(invalidate_partner_cache, flattened_set))

            # Todo: The below code is not working fully, there is a n+1 delay in clearing the cache
            # Now the cache is cleared fully every time to compensate

            # List all the roles of the changed Credentials
            roles = {role.party_str() for role in obj.roles.all()}

            # Invalidate the agreed partners cache to enable the new roles and disable the old ones
            list(map(invalidate_partner_cache, roles))

            # Do the same for the partners (this one comes from cache)
            invalidate_current_partners_cache()
            # Do the same again, now cache has been reset
            invalidate_current_partners_cache()

    last_update.admin_order_field = "last_connection"
    last_update.short_description = "Last connection"


@admin.register(CredentialsRole)
class CredentialsRoleAdmin(SolidModelAdmin):
    model = CredentialsRole
    list_display = ["party_long", "role", "business_details"]
    fields = ["business_details", "agreed_parties"]
    list_filter = ["role"]
    autocomplete_fields = ["agreed_parties"]
    search_fields = [
        "business_details__name",
        "business_details__website",
        "agreed_parties__country_code",
        "agreed_parties__party_id",
    ]


@admin.register(DefaultTariffs)
class DefaultTariffsAdmin(SolidModelAdmin):
    model = DefaultTariffs
    list_display = ["standard", "tariff_list"]
    autocomplete_fields = ["tariffs"]

    formfield_overrides = widgets.formfield_overrides


# admin.site.unregister(User)
admin.site.unregister(PersonalData)


@admin.register(PersonalData)
class MyPersonalDataAdmin(PersonalDataAdmin, AdminUtilityMixin):
    change_list_template = "admin/gdpr_assist/personaldata/change_list.html"

    # def changelist_view(self, *args, **kwargs):
    #     result = super().changelist_view(*args, **kwargs)
    #     return result


# @admin.register(User)
class UserAdmin(SolidNestedModelAdmin):
    class AccountAdmin(NestedStackedInline):
        class TransactionInline(NestedTabularInline):
            model = Transaction

        inlines = [TransactionInline]
        model = Account
        ordering = ["customer"]
        search_fields = (
            "customer__username",
            "customer__first_name",
            "customer__last_name",
        )

    model = User
    inlines = [AccountAdmin]
    list_display = ("username", "first_name", "last_name", "balances", "app_token_ids")
    search_fields = ("username", "first_name", "last_name")
    fields = ("first_name", "last_name", "email", "is_active")

    def balances(self, obj):
        if not obj or not obj.accounts.exists():
            return "-"
        return format_html(
            "<br>".join(
                [
                    f"{account.balance}{account.currency}"
                    for account in obj.accounts.all()
                ]
            )
        )

    def app_token_ids(self, obj):
        return format_html(
            "<br>".join([account.app_token_id for account in obj.accounts.all()])
        )


@admin.register(Payment)
class PaymentAdmin(SolidModelAdmin):
    model = Payment
    exclude = []
    list_display = ("status", "email", "amount", "currency", "created")
    search_fields = ("amount", "payment_method__customer__user__email")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Authorization)
class AuthorizationAdmin(SolidModelAdmin):
    model = Authorization
    exclude = []
    list_display = ("authorization_reference", "session", "max_price", "created")
    search_fields = ("authorization_reference", "session__uid")

    formfield_overrides = widgets.formfield_overrides

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Token, TokenAdmin)
admin.site.register(Location, LocationAdmin)
admin.site.register(Evse, EvseAdmin)
admin.site.register(Tariff, TariffAdmin)
admin.site.register(Cdr, CdrAdmin)
admin.site.register(Session, SessionAdmin)
admin.site.register(Credentials, CredentialsAdmin)
