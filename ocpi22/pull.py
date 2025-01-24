from django.utils.translation import gettext_lazy as _

import ocpi22.logging as logging

from django.conf import settings

from ocpi22.messages import messages
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.models.location import Location
from ocpi22.choices import EndpointRoleEnum
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.tasks import pull_objects
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id

# Todo: Full object pull for Cdrs and Sessions


def schedule_full_update(credentials: Credentials, countdown=1, limit=2):
    if not credentials.is_complete() or not credentials.valid:
        logging.warning(
            f"Not doing a full update for an invalid Credentials: {credentials}"
        )
        return
    logging.info(f"Scheduling full update: {credentials}")
    endpoints = credentials.endpoints
    if not endpoints.count():
        return
    object_list = [
        dict(
            model="ocpi22.models.tariffs.Tariff",
            viewset="ocpi22.ocpi.api.TariffViewSet",
            url=getattr(
                endpoints.filter(
                    role=EndpointRoleEnum.SENDER.value,
                    identifier=Tariff.ocpi_module_name.value,
                ).first(),
                "url",
                "",
            ),
        ),
        dict(
            model="ocpi22.models.tokens.Token",
            viewset="ocpi22.ocpi.api.TokenViewSet",
            url=getattr(
                endpoints.filter(
                    role=EndpointRoleEnum.SENDER.value,
                    identifier=Token.ocpi_module_name.value,
                ).first(),
                "url",
                "",
            ),
        ),
        dict(
            model="ocpi22.models.locations.Location",
            viewset="ocpi22.locations.location.LocationViewSet",
            url=getattr(
                endpoints.filter(
                    role=EndpointRoleEnum.SENDER.value,
                    identifier=Location.ocpi_module_name.value,
                ).first(),
                "url",
                "",
            ),
        ),
    ]
    token = credentials.theirs_base64()
    role: CredentialsRole = credentials.roles.first()
    kwargs = dict(
        token_base64=token,
        to_country_code=role.country_code,
        to_party_id=role.party_id,
        from_country_code=get_our_country_code(),
        from_party_id=get_our_party_id(),
        method="get",
        limit=limit,
        credentials_id=credentials.pk,
    )
    if settings.BACKGROUND_SEND:
        pull_objects.apply_async(
            (object_list,),
            kwargs=kwargs,
            countdown=countdown,
            retry=True,
            retry_policy=dict(max_retries=3, interval_start=60 * 5),
        )
    else:
        pull_objects(object_list, **kwargs)


def admin_pull_all(modeladmin, request, queryset):
    for credentials in queryset.all():
        schedule_full_update(credentials)
    messages.success(
        request, _("Full update queued for {} parties").format(queryset.count())
    )


admin_pull_all.short_description = _("Fetch all data from selected roaming partners")
