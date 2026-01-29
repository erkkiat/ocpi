from dataclasses import dataclass

from ocpi22.models.credentials import CredentialsRole, Credentials
from ocpi22.models.token import Token


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

@dataclass
class TokenDto:
    uid: str
    adhoc: bool
    token: Token | None