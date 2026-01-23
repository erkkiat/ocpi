import logging
from typing import Optional
from django.conf import settings

from ocpi22.cpo.repositories import CredentialsRepository
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Evse
from ocpiconnector.party import Party

logger = logging.getLogger(__name__)


class CredentialsService:
    @staticmethod
    def is_location_allowed(credentials: Credentials, location_uid: str) -> bool:
        allowed_locations = credentials.allowed_locations
        if not allowed_locations:
            return True

        return location_uid in allowed_locations

    @staticmethod
    def is_evse_allowed(credentials: Credentials, evse: Evse) -> bool:
        location_uid = evse.location.uid
        return CredentialsService.is_location_allowed(credentials, location_uid)

    @staticmethod
    def find_credentials(party: Party) -> Optional[Credentials]:
        roles = CredentialsRepository.get_roles_by_party(party)
        if not roles:
            return None

        credentials_list = [role.credentials for role in roles if role.credentials]
        if not credentials_list:
            return None
        if len(credentials_list) > 1:
            logger.error(
                f"{settings.HOSTNAME}: Multiple Credentials for {str(party)} in the database"
            )
        credentials = credentials_list[0]
        if not credentials.valid:
            return None

        return credentials

    @staticmethod
    def get_hubject_priority_rank() -> int:
        role = CredentialsRepository.find_hubject_credentials_role()
        if not role:
            raise ValueError("Hubject Credentials Role not found")

        return role.credentials.auth_priority
