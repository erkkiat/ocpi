import os

from ocpiconnector.ocpi_identities import ocpi_identities


def export_environment_variables(_request):
    return dict(
        country_code=os.environ.get('COUNTRY_CODE'),
        party_id=os.environ.get('PARTY_ID'),
        header_color=os.environ.get('HEADER_COLOR'),
        roles=" / ".join([f'{key}: {value}' for key, value in ocpi_identities.items()]),
    )
