import asyncio
import logging
import time

from aiohttp import ClientSession
from django.conf import settings

from integrations.hubject.services import HubjectService
from ocpi22.choices import AuthorizationEnum
from ocpi22.credentials.services import CredentialsService

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

    def start_all_tasks(
        self, party_details, session, data, token_id
    ) -> dict[asyncio.Task, int]:
        tasks_map: dict[asyncio.Task, int] = {}
        hubject_rank = CredentialsService.get_hubject_prioriry_rank()

        lower_ranked_parties = []
        for p in party_details:
            if p["rank"] < hubject_rank:
                t = self._start_task(session, p, data)
                tasks_map[t] = p["rank"]
            else:
                lower_ranked_parties.append(p)

        t = self._start_hubject_task(token_id)
        if t:
            tasks_map[t] = hubject_rank

        for p in lower_ranked_parties:
            t = self._start_task(session, p, data)
            tasks_map[t] = p["rank"]

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
        tasks_map = self.start_all_tasks(party_details, session, data, token_id)

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
