from dataclasses import dataclass

from ocpi22.models.credentials import CredentialsRole, Credentials


@dataclass
class PartyDetails:
    url: str
    headers: dict[str, str]
    ssl: object | None
    ocpi_master: CredentialsRole
    party_id: str
    country_code: str
    credentials: Credentials
    task_name: str
    auth_priority: int
