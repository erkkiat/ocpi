from datetime import datetime
from typing import Optional

import pytz
from django.db.models import FloatField

from ocpi22.commands.serializers import CommandResultType
from ocpi22.commands.services import CallBackService
from ocpi22.cpo.services import logger
from ocpi22.models.enum import AuthMethodChoices
from ocpi22.models.session import Session


class SessionService:
    @staticmethod
    def is_auth_method_remote_command(session: Session) -> bool:
        return session and session.auth_method == AuthMethodChoices.COMMAND

    @staticmethod
    def start_command_session(
        session: Session, start_kwh: FloatField
    ) -> tuple[bool, Optional[str]]:
        try:
            session.status = Session.ACTIVE
            session.start_kwh = start_kwh
            session.save(update_fields=["status", "start_kwh"])
            session.send_updates()
            CallBackService().send_callback(
                session=session,
                result=CommandResultType.ACCEPTED,
            )

            return True, None
        except Exception:
            logger.exception(f"Error starting COMMAND session {session.id}")
            message = "Internal error starting session"

            try:
                CallBackService().send_callback(
                    session=session, result=CommandResultType.REJECTED, message=message
                )
            except Exception:
                logger.exception(
                    f"Failed to send rejection callback for session {session.uid}"
                )

            return False, message

    @staticmethod
    def stop_command_session(
        session: Session, stop_kwh: Optional[float], stop_timestamp: datetime
    ) -> tuple[bool, Optional[str]]:
        try:
            if stop_kwh:
                session.stop_kwh = stop_kwh

            session.update_charging_periods(kwh=session.kwh, timestamp=stop_timestamp)
            session.status = Session.COMPLETED
            session.end_date_time = stop_timestamp.replace(tzinfo=pytz.utc)
            session.last_updated = datetime.now(pytz.utc)
            session.calculate_price()
            session.save(
                update_fields=[
                    "stop_kwh",
                    "status",
                    "last_updated",
                    "end_date_time",
                    "total_cost_incl_vat",
                    "total_cost_excl_vat",
                ]
            )
            session.send_updates()

            CallBackService().send_callback(
                session=session,
                result=CommandResultType.ACCEPTED,
            )

            return True, None
        except Exception:
            logger.exception(f"Error stopping COMMAND session {session.id}")
            message = "Internal error stopping session"

            try:
                CallBackService().send_callback(
                    session=session, result=CommandResultType.REJECTED, message=message
                )
            except Exception:
                logger.exception(
                    f"Failed to send rejection callback for session {session.uid}"
                )

            return False, message
