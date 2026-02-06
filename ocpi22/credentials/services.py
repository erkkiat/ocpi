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
    def invalidate_credentials_caches() -> None:
        logger.info("Invalidating credentials caches")

        try:
            from ocpi22.credentials.util import find_endpoints_by_roles

            find_endpoints_by_roles.cache_clear()
        except Exception:
            logger.exception("Failed to clear find_endpoints_by_roles cache")

        try:
            from ocpi22.ocpi.auth import find_credentials

            find_credentials.cache_clear()
        except Exception:
            logger.exception("Failed to clear find_credentials cache")

        try:
            from ocpi22.tokens.auth import _authorize_token

            _authorize_token.cache_clear()
        except Exception:
            logger.exception("Failed to clear _authorize_token cache")

    @staticmethod
    def invalidate_credentials_role_caches() -> None:
        logger.info("Invalidating credentials role caches")

        try:
            from ocpi22.credentials.util import find_endpoints_by_roles

            find_endpoints_by_roles.cache_clear()
        except Exception:
            logger.exception("Failed to clear find_endpoints_by_roles cache")

        try:
            from ocpi22.ocpi.auth import get_credentialsrole

            get_credentialsrole.cache_clear()
        except Exception:
            logger.exception("Failed to clear get_credentialsrole cache")

        try:
            from ocpi22.ocpi.partners import partners_cache

            partners_cache.clear()
        except Exception:
            logger.exception("Failed to clear partners_cache")

        try:
            from ocpi22.models.credentials import is_hub_cache

            is_hub_cache.clear()
        except Exception:
            logger.exception("Failed to clear is_hub_cache")

    @staticmethod
    def invalidate_all_caches() -> None:
        CredentialsService.invalidate_credentials_caches()
        CredentialsService.invalidate_credentials_role_caches()

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
