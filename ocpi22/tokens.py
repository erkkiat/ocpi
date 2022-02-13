import logging

from django.conf import settings
from icecream import ic

from ocpi22.models.token import Token
from ocpi22.ocpi_util import ocpi_post


def authorize_token(token_uid, location=None):
    from ocpi22.models.token import Token
    from ocpi22.models.session import Session

    if settings.DEBUG and 'POSITIVE_TEST_TOKEN' in token_uid:
        return Session.WHITELIST, dict(uid=token_uid, type=Token.RFID, contract_id='123')

    token: Token = Token.get_if_exists(uid=token_uid)
    if token and token.whitelist in (Token.ALLOWED, Token.ALWAYS):
        from ocpi22.api import TokenSerializer
        serializer = TokenSerializer(instance=token)
        return Session.WHITELIST, serializer.data
    # noinspection PyUnresolvedReferences
    endpoints = Endpoint.objects.filter(identifier=Endpoint.TOKENS, role=Endpoint.SENDER)
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
        if result.status_code == 403:
            logging.warning(f'No authorization for token {token_uid} at {location or "<not known>"} '
                            f'from {endpoint.credentials.party()}. ')
            # raise exception.PermissionDenied("You don't have enough balance on your account.")
        if result.status_code == 200:
            data = result.json()
            # ic(data)
            return Session.AUTH_REQUEST, data.get('data').get('AuthorizationInfo')
    logging.warning(f'No authorization for token {token_uid} at {location or "<not known>"} from any party. '
                    'Someone may be trying to use a credit card or some other unsuitable payment device.')
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
