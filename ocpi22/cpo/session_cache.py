import logging

from django.conf import settings

from ocpi22.cpo.mqtt.schemas import CachedSession
from util import RedisStore

logger = logging.getLogger(__name__)

session_store = RedisStore(namespace=settings.REDIS_SESSION_CACHE_NAMESPACE)


def get_cached_session(session_id) -> CachedSession | None:
    try:
        return session_store.retrieve(session_id)
    except KeyError:
        logger.warning(f"Session {session_id} not found in RedisStore.")
        return None


def save_to_session_cache(route, session, meter_value_update_date_time=None):
    cached_session = CachedSession(
        session_id=session.uid,
        kwh=session.kwh,
        timestamp=session.last_updated,
        route_to_msp=route,
        meter_value_update_date_time=meter_value_update_date_time,
    )
    store_session_cache(cached_session)


def store_session_cache(cached_session):
    """Use save_to_session_cache, unless you already have a cached session object iniatialized"""
    session_store.store(
        cached_session.session_id,
        cached_session,
        expiration=settings.MAXIMUM_CHARGE_SESSION_LENGTH_IN_SECONDS,
    )
