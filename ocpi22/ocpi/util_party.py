from functools import lru_cache
from typing import Optional

from logging import getLogger

from ocpiconnector.party import Party

logger = getLogger(__name__)


def get_sender_party(
    headers,
    country_code_key="HTTP_OCPI_FROM_COUNTRY_CODE",
    party_id_key="HTTP_OCPI_FROM_PARTY_ID",
) -> Party:
    """
    >>> get_sender_party({'Ocpi-From-Country-Code': 'FI', 'Ocpi-From-Party-Id': 'EON'})
    Party(country_code='FI', party_id='EON')
    >>> get_sender_party({'HTTP_OCPI_FROM_COUNTRY_CODE': 'FI', 'HTTP_OCPI_FROM_PARTY_ID': 'EON'})
    Party(country_code='FI', party_id='EON')
    >>> get_sender_party({'ocpi-from-country-code': 'fi', 'ocpi-from-party-id': 'eon'})
    Party(country_code='FI', party_id='EON')
    >>> str(get_sender_party({'Ocpi-From-Country-Code': 'FI', 'Ocpi-From-Party-Id': 'EON'}))
    'FI*EON'
    """
    if not headers:
        logger.error("No headers from sender")
        return Party("", "")
    headers = dict_keys_to_lower_and_filter(headers, "ocpi")
    country_code = headers.get(
        country_code_key.lower(),
        headers.get(_secondary_header_name(country_code_key), ""),
    ).upper()
    party_id = headers.get(
        party_id_key.lower(), headers.get(_secondary_header_name(party_id_key), "")
    ).upper()
    return Party(country_code, party_id)


def get_to_party(headers) -> Party:
    """
    >>> get_to_party({'Ocpi-To-Country-Code': 'FI', 'Ocpi-To-Party-Id': 'EON'})
    Party(country_code='FI', party_id='EON')
    >>> get_to_party({'HTTP_OCPI_TO_COUNTRY_CODE': 'FI', 'HTTP_OCPI_TO_PARTY_ID': 'EON'})
    Party(country_code='FI', party_id='EON')
    """
    return get_sender_party(
        headers, "HTTP_OCPI_TO_COUNTRY_CODE", "HTTP_OCPI_TO_PARTY_ID"
    )


def dict_keys_to_lower_and_filter(d: dict, filter_word: str) -> Optional[dict]:
    """
    >>> dict_keys_to_lower_and_filter({'OCPI-this': 'that', 'ocpi-THAT': 'THIS', 'others': 'ignored'}, 'ocpi')
    {'ocpi-this': 'that', 'ocpi-that': 'THIS'}
    """
    if not d:
        return None
    return dict(
        (key.lower(), value) for key, value in d.items() if filter_word in key.lower()
    )


@lru_cache(maxsize=None)
def _secondary_header_name(header_name: str) -> str:
    """
    >>> _secondary_header_name('HTTP_OCPI_FROM_COUNTRY_CODE')
    'ocpi-from-country-code'
    >>> _secondary_header_name('http_ocpi_to_party_id')
    'ocpi-to-party-id'
    """
    return header_name.replace("_", "-").lower().replace("http-", "")
