from logging import getLogger

import pytz
from django.db.models import F
from django.utils.datetime_safe import datetime

from ocpi22.models.session import Session

logger = getLogger(__name__)


def close_active_sessions_for_evse(evse_uid: str):
    # evse = get_evse_object(evse)
    active_sessions = Session.objects.filter(
        evse__uid=evse_uid, status__in=(Session.ACTIVE, Session.PENDING)
    )
    active_sessions.update(
        last_updated=datetime.now(pytz.utc),
        status=Session.COMPLETED,
        end_date_time=F("last_updated"),
    )

    for session in active_sessions:
        session.send_updates()
        logger.error(
            f"Completed active Session {session.uid} which has been left hanging"
        )
