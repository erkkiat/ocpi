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
from ocpi22.models.token import Token
from ocpi22.tokens.auth import _authorize_token
from ocpi22.tokens.dataclasses import TokenDto


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

    def update_meter_values(
        self,
        session: Session,
        timestamp: datetime,
        kwh: float,
        soc: float | None = None,
        power: float | None = None,
    ) -> None:
        if session.start_kwh == 0:
            session.start_kwh = kwh
        session.stop_kwh = kwh
        session.calculate_price()
        session.update_last_updated()
        kwh_delta = float(session.stop_kwh) - float(session.start_kwh)
        session.update_charging_periods(kwh_delta, soc, power, timestamp)
        session.save(
            update_fields=[
                "start_kwh",
                "stop_kwh",
                "total_cost_incl_vat",
                "total_cost_excl_vat",
                "last_updated",
            ]
        )

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

        self._clear_token_authorization_cache(session)
        logger.info(
            f"Stopped session {session.uid} at {timestamp} with {session.kwh} kWh and "
            f"cost {session.total_cost_incl_vat} {session.currency}"
        )

    @staticmethod
    def _clear_token_authorization_cache(session: Session) -> None:
        token_uid = session.cdr_token.uid
        try:
            token = Token.objects.get(uid=token_uid)
            token_dto = TokenDto(uid=token_uid, adhoc=False, token=token)
        except Token.DoesNotExist:
            token_dto = TokenDto(uid=token_uid, adhoc=True, token=None)
        _authorize_token.clear_cache_item(
            token_dto,
            session.location,
            request=None,
            evse_id=session.evse.evse_id if session.evse else None,
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
