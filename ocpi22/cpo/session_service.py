from datetime import datetime

import pytz
from django.db import transaction
from django.db.models import FloatField

from ocpi22.commands.serializers import CommandResultType
from ocpi22.commands.services import send_callback
from ocpi22.cpo.services import logger, CdrService
from ocpi22.cpo.session_cache import get_cached_session
from ocpi22.models.enum import AuthMethodChoices
from ocpi22.models.location import Connector
from ocpi22.models.session import Session


class SessionService:
    @staticmethod
    def is_auth_method_remote_command(session: Session) -> bool:
        return session and session.auth_method == AuthMethodChoices.COMMAND

    def start_session(self, session: Session, start_kwh: float) -> None:
        session.status = Session.ACTIVE
        session.start_kwh = start_kwh
        session.save(update_fields=["status", "start_kwh"])

    def start_command_session(self, session: Session, start_kwh: FloatField) -> None:
        original_status = session.status
        session.status = Session.ACTIVE
        session.start_kwh = start_kwh
        session.stop_kwh = start_kwh
        session.save(update_fields=["status", "start_kwh", "stop_kwh"])
        if session.route_through_oicp:
            return
        if original_status != Session.PENDING:
            logger.info("Cannot send ACCEPTED callback for non-pending session")
        send_callback.delay(
            session_uid=session.uid,
            result=CommandResultType.ACCEPTED.value,
        )
        return

    def stop_and_create_cdr(
        self,
        session: Session,
        stop_kwh: float | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        if not timestamp:
            timestamp = datetime.now(pytz.utc)
        with transaction.atomic():
            self.set_stop_kwh(session, stop_kwh)
            session.update_charging_periods(kwh=session.kwh, timestamp=timestamp)
            session.status = Session.COMPLETED
            session.end_date_time = timestamp.replace(tzinfo=pytz.utc)
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

            CdrService.get_or_create_cdr(session)

        logger.info(
            f"Stopped session {session.uid} at {timestamp} with {session.kwh} kWh and "
            f"cost {session.total_cost_incl_vat} {session.currency}"
        )

    @staticmethod
    def set_stop_kwh(session: Session, stop_kwh: float | None = None) -> None:
        if stop_kwh:
            session.stop_kwh = stop_kwh
        else:
            cached_session = get_cached_session(session.uid)
            if cached_session and cached_session.kwh > session.kwh:
                session.stop_kwh = cached_session.kwh

    def set_currency_and_start(self, session: Session, connector_id: str) -> None:
        session.connector = Connector.objects.prefetch_related(
            "tariff_ids"
        ).get_if_exists(uid=connector_id, evse=session.evse, raise_exception=True)
        session.status = Session.ACTIVE
        if session.connector.tariff_ids:
            first_tariff = session.connector.tariff_ids.first()
            if first_tariff:
                session.currency = first_tariff.currency
        session.save(
            update_fields=[
                "connector",
                "status",
                "currency",
                "start_kwh",
                "stop_kwh",
            ]
        )
        return
