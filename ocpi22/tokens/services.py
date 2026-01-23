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

TIMEOUT = 5.0


class TokenAuthorizationService:
    def __init__(self, timeout: float = TIMEOUT):
        self._timeout = timeout

    def _create_ocpi_task(
        self, session: ClientSession, party_details: PartyDetails, data
    ) -> asyncio.Task:
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
        tasks: dict[asyncio.Task, int] = {}

        for p in party_details:
            t = self._create_ocpi_task(session, p, data)
            tasks[t] = p.auth_priority

        if settings.ENABLE_HUBJECT:
            try:
                hubject_rank = await sync_to_async(
                    CredentialsService.get_hubject_auth_priority_rank
                )()
                t = self._start_hubject_task(token_id)
                tasks[t] = hubject_rank
            except ValueError:
                logger.error("Hubject Credentials Role not found, skipping Hubject authorization task")

        return tasks

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
        from ocpi22.tokens.token_async import process_task_result

        priority_by_task: dict[asyncio.Task, int] = await self.start_all_tasks(
            party_details, session, data, token_id
        )

        if not priority_by_task:
            return None

        pending_tasks = set(priority_by_task.keys())

        allowed_responses_by_priority: dict[int, dict] = {}
        first_denial: dict | None = None

        start_time = time.time()
        while pending_tasks:
            elapsed = time.time() - start_time
            remaining = self._timeout - elapsed

            if remaining <= 0:
                break

            done_tasks, pending_tasks = await asyncio.wait(
                pending_tasks, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )

            if not done_tasks:
                break

            for task in done_tasks:
                response = process_task_result(task)
                if not response:
                    continue

                is_allowed = response.get("allowed") == AuthorizationEnum.ALLOWED

                if is_allowed:
                    priority = priority_by_task[task]
                    allowed_responses_by_priority[priority] = response

                elif not first_denial:
                    first_denial = response

            if allowed_responses_by_priority:
                best_rank = min(allowed_responses_by_priority.keys())
                if not self._has_better_ranks_pending(
                    best_rank, priority_by_task, pending_tasks
                ):
                    self._cancel_pending_tasks(pending_tasks)
                    return allowed_responses_by_priority[best_rank]

        self._cancel_pending_tasks(pending_tasks)

        if allowed_responses_by_priority:
            return allowed_responses_by_priority[
                min(allowed_responses_by_priority.keys())
            ]

        return first_denial

    @staticmethod
    def build_url(base_url, token_id_param):
        return urljoin(with_trailing_slash(base_url), f"{token_id_param}/authorize")

    def build_party_details(
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
                url=self.build_url(url, token_id),
                headers=make_headers(token_b64, to=Party(cc, pid), sender=sender),
                ssl=ssl,
                ocpi_master=role,
                party_id=pid,
                country_code=cc,
                credentials=creds,
                task_name=f"{cc}*{pid}",
                auth_priority=creds.auth_priority,
            )
            party_details.append(details)

        return party_details

    async def authorize_known_token(
        self, party_details, session, data, token_id
    ) -> dict | None:
        from ocpi22.tokens.token_async import process_task_result

        party_details = party_details[0]
        task = self._create_ocpi_task(session, party_details, data)

        try:
            await task
            res = process_task_result(task)
            return res
        except Exception as e:
            logger.error(f"Error authorizing known token with owner: {e}")
            return None

    @staticmethod
    def build_default_allowed_authorization(
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
