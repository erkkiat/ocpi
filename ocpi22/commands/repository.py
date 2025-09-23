from typing import Optional
from django.db.models import Q

from ocpi22.models.session import Session
from ocpi22.util import command_store


class SessionRepository:
    def find_session_for_command(
        self,
        authorization_reference: Optional[str] = None,
        token_uid: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Session]:
        query_conditions = []

        if authorization_reference:
            query_conditions.append(Q(authorization_reference=authorization_reference))

        if token_uid:
            query_conditions.append(Q(cdr_token__uid=token_uid))

        if session_id:
            query_conditions.append(Q(uid=session_id))

        if not query_conditions:
            return None

        combined_query = query_conditions[0]
        for condition in query_conditions[1:]:
            combined_query |= condition

        return Session.get_if_exists(combined_query)

    def find_session_by_uid(self, uid: str):
        return Session.objects.filter(uid=uid).first()

    @staticmethod
    def find_session_by_auth_ref_and_token_uid(
        auth_reference: str, token_uid: str
    ) -> Optional[Session]:
        return Session.objects.filter(
            authorization_reference=auth_reference, cdr_token__uid=token_uid
        ).first()

    @staticmethod
    def find_session_by_auth_ref(auth_reference: str) -> Optional[Session]:
        return Session.objects.get(authorization_reference=auth_reference)


class CommandRepository:
    def store_command_data(self, command_id: str, command_data: dict):
        command_store[command_id] = command_data

    def get_command_data(self, command_id: str) -> Optional[dict]:
        return command_store.get(command_id)
