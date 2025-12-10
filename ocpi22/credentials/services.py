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
