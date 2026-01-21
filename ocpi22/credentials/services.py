from ocpi22.cpo.repositories import CredentialsRepository
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Evse


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
    def get_hubject_priority_rank() -> int:
        role = CredentialsRepository.find_hubject_credentials_role()
        if not role:
            raise ValueError("Hubject Credentials Role not found")

        return role.credentials.auth_priority
