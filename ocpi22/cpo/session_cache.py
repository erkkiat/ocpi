from cachetools import cached, TTLCache
from django.conf import settings

from ocpi22.choices import OcpiModuleEnum
from ocpi22.cpo.mqtt.schemas import CachedSession
from ocpi22.routing import find_route_from_credentials
from util import RedisStore

session_store = RedisStore(namespace=settings.REDIS_SESSION_CACHE_NAMESPACE)


@cached(cache=TTLCache(maxsize=0, ttl=4*60*60))
def get_cached_session(session_id) -> CachedSession:
    return session_store.retrieve(session_id)


def save_to_session_cache(credentialsrole, session, token):
    """Save a cached session to the Redis store for quick access (mainly by process_meter_values)"""
    cached_session = CachedSession(
        session_id=session.uid,
        kwh=session.kwh,
        timestamp=session.last_updated,
        route_to_msp=find_route_from_credentials(credentialsrole.credentials, OcpiModuleEnum.SESSIONS),
    )
    store_session_cache(cached_session)


def store_session_cache(cached_session):
    """Use save_to_session_cache, unless you already have a cached session object iniatialized"""
    session_store.store(cached_session.session_id, cached_session, expiration=settings.MAXIMUM_CHARGE_SESSION_LENGTH_IN_SECONDS)
