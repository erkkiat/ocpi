from integrations.hubject.api import EroamingEvseDataPushApi
from ocpi22.messages import messages
from django.utils.translation import gettext as _


def execute_hubject_full_load(creds):
    EroamingEvseDataPushApi.full_load()


def admin_push_all(modeladmin, request, queryset):
    for credentials in queryset.all():
        execute_hubject_full_load(credentials)
    messages.success(
        request, _("Full update queued for {} parties").format(queryset.count())
    )


admin_push_all.short_description = _("Push all data to selected roaming partners")
