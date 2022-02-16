from django.conf import settings

from ocpi22.models.credentials import Credentials, Endpoint, CredentialsRole
from ocpi22.models.location import Location
from ocpi22.models.tariff import Tariff
from ocpi22.models.token import Token
from ocpi22.tasks import pull_objects
from ocpiconnector.ocpi_identities import get_our_country_code, get_our_party_id


# Todo: Full object pull for Sessions and Cdrs

def schedule_full_update(credentials: Credentials, countdown=1, limit=20):
    endpoints = credentials.endpoints
    object_list = [
        dict(model='ocpi22.models.tariffs.Tariff', viewset='ocpi22.api.TariffViewSet',
             url=endpoints.filter(role=Endpoint.SENDER, identifier=Tariff.ocpi_module_name).first().url),
        dict(model='ocpi22.models.tokens.Token', viewset='ocpi22.api.TokenViewSet',
             url=endpoints.filter(role=Endpoint.SENDER, identifier=Token.ocpi_module_name).first().url),
        dict(model='ocpi22.models.locations.Location', viewset='ocpi22.location.LocationViewSet',
             url=endpoints.filter(role=Endpoint.SENDER, identifier=Location.ocpi_module_name).first().url),
    ]
    token = credentials.theirs_base64()
    role: CredentialsRole = credentials.roles.first()
    kwargs = dict(token_base64=token,
                  to_country_code=role.country_code, to_party_id=role.party_id,
                  from_country_code=get_our_country_code(), from_party_id=get_our_party_id(), method='get',
                  limit=limit)
    if settings.BACKGROUND_SEND:
        pull_objects.apply_async((object_list,), kwargs=kwargs, countdown=countdown, retry=True,
                                 retry_policy=dict(max_retries=10, interval_start=60 * 5))
    else:
        pull_objects(object_list, **kwargs)
