from ocpi22.models.credentials import CredentialsRole
from ocpiconnector.party import Party


def cleanup_credentialsrole(party: Party):
    role = CredentialsRole.get_if_exists(country_code=party.country_code, party_id=party.party_id)
    if role:
        role.credentials.endpoints.all().delete()
        role.credentials.delete()
        role.delete()
