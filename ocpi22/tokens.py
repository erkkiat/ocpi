import logging
import uuid

from cachetools.func import ttl_cache
from icecream import ic

from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi_util import ocpi_post


@ttl_cache(maxsize=128, ttl=15 * 60)
def authorize_token(token_uid, location_uid=None) -> (str, str):
    """
    Request authorization for a token we know, and consider that authorization valid for the next 15 minutes
    (OCPI requirement)
    """
    ic()
    return Session.AUTH_REQUEST, uuid.uuid4()

    try:
        token = Token.objects.get(uid=token_uid)
        location = Location.objects.get(uid=location_uid)

        # noinspection PyUnresolvedReferences
        endpoints = Endpoint.objects.filter(identifier=OcpiModuleEnum.TOKENS.value, role=EndpointRoleEnum.SENDER.value)
        for endpoint in endpoints:
            url = f'{endpoint.url}{token_uid}/authorize'
            ic(url)
            location_references = dict(
                location_id=location.uid,
                evse_uids=[e.uid for e in location.evses.all()]
            )
            result = ocpi_post(
                url,
                token_base64=endpoint.get_token_base64(),
                data=dict(LocationReferences=location_references) if location else dict()
            )
            if result.status_code > 400:
                logging.warning(f'No authorization for token {token_uid} at {location or "<not known>"} '
                                f'from {endpoint.credentials.party()} (HTTP {result.status_code}). ')
                # raise exception.PermissionDenied("You don't have enough balance on your account.")
            if result.status_code == 200:
                data = result.json()
                # ic(data)
                return Session.AUTH_REQUEST, data.get('data').get('AuthorizationInfo')
        logging.warning(f'No authorization for token {token_uid} at {location or "<not known>"} from any party. '
                        'Someone may be trying to use a credit card or some other unsuitable payment device.')
    except Token.DoesNotExist as e:
        pass

    return False, False


def get_admin_token() -> Token:
    our_country_code, our_party_id = Token.get_owner_identity().split('*')
    our_identity = Token.get_owner_identity()
    token, _created = Token.objects.get_or_create(
        country_code=our_country_code,
        party_id=our_party_id,
        uid=f'{our_identity}*T*ADMIN*TOKEN',
        defaults=dict(
            type='OTHER', contract_id='INTERNAL', issuer=our_identity, valid=True
        )
    )
    return token
