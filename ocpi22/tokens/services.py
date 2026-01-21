import asyncio
import logging
import time
from typing import TYPE_CHECKING, Union
from urllib.parse import urljoin

from aiohttp import ClientSession
from asgiref.sync import sync_to_async
from django.conf import settings

from integrations.hubject.services import HubjectService
from ocpi22.choices import AuthorizationEnum, OcpiRolesEnum
from ocpi22.credentials.services import CredentialsService
from ocpi22.choices import TokenType, MessageTexts
from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.tokens.dataclasses import PartyDetails
from ocpi22.tokens.util import get_token_id
from ocpiconnector.ocpi_identities import get_our_party
from ocpiconnector.party import Party
from util import with_trailing_slash

if TYPE_CHECKING:
    from ocpi22.tokens.auth import TokenAuthorization

logger = logging.getLogger(__name__)


class TokenAuthorizationService:
    TIMEOUT = 5.0

    def _start_task(self, session: ClientSession, party_details:PartyDetails, data) -> asyncio.Task:
        from ocpi22.tokens.token_async import post_request

        coroutine = post_request(
            session=session,
            ssl_context=party_details.ssl,
            url=party_details.url,
            data=data,
            ocpi_master=party_details.ocpi_master,
            headers=party_details.headers,
        )

        return asyncio.create_task(coroutine, name=party_details.task_name)

    def _start_hubject_task(self, token_uid: str) -> asyncio.Task | None:
        coroutine = HubjectService.post_authorize_request(
            operator_id=str(settings.HUBJECT_OPERATOR_ID),
            token_id=token_uid,
        )
        return asyncio.create_task(coroutine, name=settings.HUBJECT_OPERATOR_ID)

    async def start_all_tasks(
        self, party_details, session, data, token_id
    ) -> dict[asyncio.Task, int]:
        tasks_map: dict[asyncio.Task, int] = {}

        for p in party_details:
            t = self._start_task(session, p, data)
            tasks_map[t] = p["rank"]

        if settings.ENABLE_HUBJECT:
            hubject_rank = await sync_to_async(
                CredentialsService.get_hubject_priority_rank
            )()
            t = self._start_hubject_task(token_id)
            tasks_map[t] = hubject_rank

        return tasks_map

    def _process_completed_task(
        self,
        task: asyncio.Task,
        tasks_map: dict[asyncio.Task, int],
        candidates: dict[int, dict],
        first_denial: dict | None,
        pending: set[asyncio.Task],
    ) -> tuple[dict | None, dict | None]:
        from ocpi22.tokens.token_async import process_task_result

        rank = tasks_map[task]
        res = process_task_result(task)

        if res and res.get("allowed") == AuthorizationEnum.ALLOWED:
            candidates[rank] = res

            # Best possible response
            if rank == 0:
                self._cancel_pending_tasks(pending)
                return res, first_denial

            if not self._has_better_ranks_pending(rank, tasks_map, pending):
                self._cancel_pending_tasks(pending)
                return res, first_denial
        else:
            if not first_denial and res:
                first_denial = res

        return None, first_denial

    def _has_better_ranks_pending(
        self,
        current_rank: int,
        tasks_map: dict[asyncio.Task, int],
        pending: set[asyncio.Task],
    ) -> bool:
        return any(tasks_map[pt] < current_rank for pt in pending)

    def _cancel_pending_tasks(self, pending: set[asyncio.Task]) -> None:
        for task in pending:
            task.cancel()

    def _check_winner_among_candidates(
        self,
        candidates: dict[int, dict],
        tasks_map: dict[asyncio.Task, int],
        pending: set[asyncio.Task],
    ) -> dict | None:
        if not candidates:
            return None

        best_rank = min(candidates.keys())
        if not self._has_better_ranks_pending(best_rank, tasks_map, pending):
            self._cancel_pending_tasks(pending)
            return candidates[best_rank]

        return None

    async def authorize_adhoc_token(
        self, party_details, session, data, token_id
    ) -> dict | None:
        start_time = time.time()

        # task -> rank
        tasks_map = await self.start_all_tasks(party_details, session, data, token_id)

        if not tasks_map:
            return None

        pending = set(tasks_map.keys())

        candidates = {}  # rank -> response
        first_denial = None

        while pending:
            elapsed = time.time() - start_time
            remaining = self.TIMEOUT - elapsed

            if remaining <= 0:
                break

            done, pending = await asyncio.wait(
                pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )

            if not done:
                break

            for task in done:
                early_return, first_denial = self._process_completed_task(
                    task, tasks_map, candidates, first_denial, pending
                )
                if early_return:
                    return early_return

            winner = self._check_winner_among_candidates(candidates, tasks_map, pending)
            if winner:
                return winner

        self._cancel_pending_tasks(pending)

        if candidates:
            return candidates[min(candidates.keys())]

        return first_denial

    @staticmethod
    def make_url(base_url, token_id_param):
        return urljoin(with_trailing_slash(base_url), f"{token_id_param}/authorize")

    def get_party_details(
        self,
        parties: list[tuple],
        ssl_contexts: list,
        prefetched_roles: list,
        token: Union[str, Token],
    ) -> list[PartyDetails]:
        from ocpi22.ocpi.headers import make_headers

        sender = get_our_party(OcpiRolesEnum.CPO)
        token_id = get_token_id(token)

        party_details = []

        for (url, token_b64, cc, pid, creds), ssl, role in zip(
            parties, ssl_contexts, prefetched_roles
        ):
            details = PartyDetails(
                url=self.make_url(url, token_id),
                headers=make_headers(
                    token_b64, to=Party(cc, pid), sender=sender
                ),
                ssl=ssl,
                ocpi_master=role,
                party_id=pid,
                country_code=cc,
                credentials=creds,
                task_name=f"{cc}*{pid}",
                auth_priority=creds.rank,
            )
            party_details.append(details)

        return party_details

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
