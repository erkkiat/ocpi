from typing import Optional

from django.contrib.auth.decorators import permission_required
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _
from django.http import HttpResponseRedirect, HttpResponse

from hub.settings import list_parties_template
from ocpi22.messages import messages
from ocpi22.ocpi.partners import (
    get_partners_by_party,
    partners_cache,
    invalidate_partner_cache,
)


@permission_required("ocpi22.can_add_roaming_partners")
def list_roaming_parties(request, role: Optional[int] = None) -> HttpResponse:
    """
    List the parties that could roam with the given party

    @param request: The request object
    @param role: The ID of the CredentialsRole
    @return: Rendered HTML page
    """
    from ocpi22.models.credentials import CredentialsRole

    ownrole = get_object_or_404(CredentialsRole, pk=role)
    partners_cache.clear()
    partners = get_partners_by_party(ownrole)
    parties = (
        CredentialsRole.objects.exclude(pk__in=partners)
        .exclude(pk=ownrole.pk)
        .exclude(country_code="")
        .exclude(party_id="")
        .order_by("country_code", "party_id")
    )
    return render(
        request,
        list_parties_template,
        {"ownrole": ownrole, "parties": parties, "partners": partners},
    )


@permission_required("ocpi22.can_add_roaming_partners")
def add_roaming_agreement(request, role1, role2) -> HttpResponse:
    """
    Add a roaming agreement link between two parties

    @param request:
    @param role1:
    @param role2:
    @return:
    """

    from ocpi22.models.credentials import CredentialsRole

    credentialsrole1 = get_object_or_404(CredentialsRole, pk=role1)
    credentialsrole2 = get_object_or_404(CredentialsRole, pk=role2)
    credentialsrole1.agreed_parties.add(credentialsrole2)
    invalidate_partner_cache(credentialsrole1)
    invalidate_partner_cache(credentialsrole2)
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


@permission_required("ocpi22.can_delete_roaming_partners")
def remove_roaming_agreement(request, role1, role2) -> HttpResponse:
    """
    Remove the roaming agreement link between two parties

    @param request: The request object
    @param role1: The ID of the first party of the roaming agreement
    @param role2: The ID of the second party
    @return: A HTTP redirect to the previous page
    """
    from ocpi22.models.credentials import CredentialsRole

    credentialsrole1 = get_object_or_404(CredentialsRole, pk=role1)
    credentialsrole2 = get_object_or_404(CredentialsRole, pk=role2)
    success = False
    # Which one is marked as the other's partner?
    if credentialsrole2 in credentialsrole1.agreed_parties.all():
        success = credentialsrole1.agreed_parties.remove(credentialsrole2)
    if credentialsrole1 in credentialsrole2.agreed_parties.all():
        success = success or credentialsrole2.agreed_parties.remove(credentialsrole1)
    if success:
        messages.success(
            request,
            _("Roaming agreement between {role1} and {role2} removed").format(
                role1=credentialsrole1, role2=credentialsrole2
            ),
        )
    else:
        messages.error(
            request,
            _("Unable to find roaming partnership between {role1} and {role2}.").format(
                role1=credentialsrole1, role2=credentialsrole2
            ),
        )
    invalidate_partner_cache(credentialsrole1)
    invalidate_partner_cache(credentialsrole2)
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
