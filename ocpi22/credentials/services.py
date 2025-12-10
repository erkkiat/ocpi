from ocpi22.models.credentials import Credentials


class CredentialsService:
    @staticmethod
    def is_location_allowed(credentials: Credentials, location_uid: str) -> bool:
        allowed_locations = credentials.allowed_locations
        if not allowed_locations:
            return True

        return location_uid in allowed_locations
