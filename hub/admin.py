from itertools import chain

from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

import widgets
from hub.admin_sites import hub_admin_site
from hub.settings import credentials_change_form_template
from ocpi22.models.credentials import Credentials
from ocpi22.pull import admin_pull_all


class CredentialsAdmin(admin.ModelAdmin):
    model = Credentials
    list_display = ["name", "party_str", "valid", "responding"]
    readonly_fields = [
        "theirs_base64",
        "ours_base64",
        "last_updated",
        "created",
        "last_connection",
    ]
    search_fields = [
        "roles__party_id",
        "roles__country_code",
        "ours",
        "theirs",
        "token_a",
        "roles__business_details__name",
    ]
    list_display_links = ["name"]
    change_form_template = credentials_change_form_template
    formfield_overrides = widgets.formfield_overrides
    actions = [admin_pull_all]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if not request.user.has_perms(["ocpi22.can_change_roaming_partners"]):
            return HttpResponse(
                _(
                    "You do not have permission to change the partners of a roaming agreement."
                ),
                status=403,
            )
        extra_context = extra_context or {}
        credentials = get_object_or_404(Credentials, pk=object_id)
        roles = credentials.roles.exclude(credentials__isnull=True).exclude(
            credentials__pk__isnull=True
        )
        extra_context.update(dict(roles=roles))
        partners = dict(
            (
                role,
                set(
                    chain(
                        role.agreed_parties.all(), role.agreed_parties_backwards.all()
                    )
                ),
            )
            for role in roles
        )
        extra_context.update(dict(partners=partners))

        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    # def has_add_permission(self, request, obj=None):
    #     return False
    #
    # def has_delete_permission(self, request, obj=None):
    #     return obj and obj.referenced_locations() == 0 and obj.referenced_credentials() == 0
    #
    # def has_change_permission(self, request, obj=None):
    #     return False


hub_admin_site.register(Credentials, CredentialsAdmin)
