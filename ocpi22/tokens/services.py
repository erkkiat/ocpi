import asyncio
import logging
from typing import TYPE_CHECKING

from aiohttp import ClientSession
from django.conf import settings

from integrations.hubject.services import HubjectService
from ocpi22.choices import TokenType, MessageTexts
from ocpi22.models.session import Session
from ocpi22.ocpi.dataclasses import AdhocToken

if TYPE_CHECKING:
    from ocpi22.tokens.auth import TokenAuthorization

logger = logging.getLogger(__name__)


class TokenAuthorizationService:
    TIMEOUT = 5.0

    def _start_task(self, session: ClientSession, party_details, data) -> asyncio.Task:
        from ocpi22.tokens.token_async import post_request

        coroutine = post_request(
            session=session,
            ssl_context=party_details["ssl"],
            url=party_details["url"],
            data=data,
            ocpi_master=party_details["ocpi_master"],
            headers=party_details["headers"],
        )

        return asyncio.create_task(coroutine, name=party_details["task_name"])

    def _start_hubject_task(self, token_uid: str) -> asyncio.Task | None:
        if settings.ENABLE_HUBJECT:
            coroutine = HubjectService.post_authorize_request(
                operator_id=str(settings.HUBJECT_OPERATOR_ID),
                token_id=token_uid,
            )
            return asyncio.create_task(coroutine, name=settings.HUBJECT_OPERATOR_ID)
        return None

    async def authorize_known_token(
        self, party_details, session, data, token_id
    ) -> dict | None:
        from ocpi22.tokens.token_async import process_task_result

        party_details = party_details[0]
        task = self._start_task(session, party_details, data)

        try:
            await task
            res = process_task_result(task)
            return res
        except Exception as e:
            logger.error(f"Error authorizing known token with owner: {e}")
            return None

    @staticmethod
    def get_default_allowed_authorization(
        session: Session, token_uid: str
    ) -> "TokenAuthorization":
        from ocpi22.tokens.auth import TokenAuthorization

        return TokenAuthorization(
            allowed="ALLOWED",
            info=MessageTexts.get("TOKEN_ACCEPTED"),
            token=AdhocToken(
                billed_to=session.billed_to.get_party(),
                uid=token_uid,
                type=TokenType.AD_HOC_USER.value,
                ocpi_master=session.billed_to,
            ),
            responding_party=session.credentials.roles.first().party_str(),  # This leads to the Credentials
            authorization_reference=session.authorization_reference,
            auth_method=session.auth_method,
            billed_to=session.billed_to.party_str(),
            msp=session.billed_to,
        )
