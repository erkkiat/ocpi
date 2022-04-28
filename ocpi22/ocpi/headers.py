from ocpiconnector.ocpi_identities import Party


def make_headers(token_base64: str, to: Party = None, sender: Party = None, extra: dict = None) -> dict:
    """
    >>> make_headers('123456', Party('TO', 'TOO'), Party('FR', 'FRM'))
    {'Authorization': 'Token 123456', 'content-type': 'application/json', 'OCPI-from-country-code': 'FR', 'OCPI-from-party-id': 'FRM', 'OCPI-to-country-code': 'TO', 'OCPI-to-party-id': 'TOO'}
    >>> make_headers('123456', extra=dict(HTTP_OCPI_TO_COUNTRY_CODE='FI', HTTP_OCPI_TO_PARTY_ID='EON'))
    {'Authorization': 'Token 123456', 'content-type': 'application/json', 'ocpi-to-country-code': 'FI', 'ocpi-to-party-id': 'EON'}

    @param token_base64: OCPI Credentials Token in base64
    @param to: Recipient party
    @param sender: Sender party
    @param extra: Any additional headers
    @return: HTTP headers ready for sending
    """
    result = {
        "Authorization": f'Token {token_base64}',
        'content-type': 'application/json',
    }
    if extra:
        for key, value in extra.items():
            result[key.replace('HTTP_', '').replace('_', '-').lower()] = value
    if to and sender:
        result.update({
            "OCPI-from-country-code": sender.country_code, "OCPI-from-party-id": sender.party_id,
            "OCPI-to-country-code": to.country_code, "OCPI-to-party-id": to.party_id,
        })
    return result
