from logging import getLogger
from typing import Optional, Dict, Any

from django.core.exceptions import ValidationError
from rest_framework import status
from starlette.status import HTTP_200_OK

from ocpi22.commands.repository import SessionRepository
from ocpi22.commands.serializers import CommandResponse
from ocpi22.models.session import Session
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.ocpi.util import OCPIResponse, Ocpi
from ocpi22.ocpi.util_party import get_sender_party
from ocpi22.util import command_store
from ocpi22.choices import MessageTexts
from ocpi22.ocpi.auth import get_credentialsrole

from webhooks.choices import RemoteCommandType
from webhooks.repository import WebhookRepository

from webhooks.services import WebhookEventService, WebhookExecutionService
from webhooks.models import WebhookEventType
from rest_framework.reverse import reverse
from ocpi22.util import build_absolute_uri, generate_random_token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.sessions.util import create_session
from ocpi22.models import enum
from ocpi22.cpo.api import close_active_sessions_for_evse

from ocpiconnector.party import Party

logger = getLogger(__name__)


class InvalidSenderPartyError(Exception):
    pass


class RemoteCommandServices:
    def get_validated_sender_party(self, request_meta: Dict[str, Any]) -> Party | None:
        sender_party = get_sender_party(request_meta)

        if not isinstance(sender_party, Party) and len(str(sender_party)) != 6:
            raise InvalidSenderPartyError(
                f"Sender party must be a Party object, got: {type(sender_party)}"
            )
        return sender_party

    def create_ocpi_response(self, webhook_response, command_name):
        timeout = webhook_response.get("timeout", 60)
        result = webhook_response.get("data", {}).get("result", "REJECTED").upper()

        message = MessageTexts.get(
            f"{command_name}_{result}",  # e.g., "START_ACCEPTED"
            MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT", "Command processed"),
        )

        if result == "ACCEPTED":
            ocpi_status = Ocpi.OK
            http_status = status.HTTP_200_OK
        else:
            ocpi_status = 2000
            http_status = status.HTTP_200_OK

        response_serializer = CommandResponse(
            data={"result": result, "timeout": timeout, "message": message}
        )

        if not response_serializer.is_valid():
            logger.error(f"Response serializer error: {response_serializer.errors}")
            return OCPIResponse(
                None,
                status_message="Internal error",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return OCPIResponse(
            response_serializer.data, status_code=ocpi_status, http_status=http_status
        )

    def send_webhook_and_save_event(self, webhook, payload, command_type):
        event_type_mapping = {
            RemoteCommandType.START_SESSION: WebhookEventType.REMOTE_START_REQUESTED,
            RemoteCommandType.STOP_SESSION: WebhookEventType.REMOTE_STOP_REQUESTED,
        }

        event_type = event_type_mapping.get(
            command_type,
            f"remote_command.{str(command_type).lower()}_requested",
        )

        event = WebhookEventService.create_event(
            webhook=webhook, event_type=event_type, payload=payload
        )
        response_json = WebhookExecutionService().execute_webhook_event(event)
        return response_json


class StartCommandService(RemoteCommandServices):
    def __init__(self):
        super().__init__()
        self.webhook_repo = WebhookRepository()
        self.session_repo = SessionRepository()

    @staticmethod
    def _create_new_session(
        credentials: Credentials,
        validated_data: Dict[str, Any],
        billed_to: CredentialsRole,
    ) -> Session:
        evse_uid = validated_data.get("evse_uid")
        close_active_sessions_for_evse(evse_uid)
        session = create_session(
            location_id=validated_data["location_id"],
            evse_uid=validated_data.get("evse_uid"),
            connector_id=validated_data.get("connector_id"),
            billed_to=billed_to.get_party(),
            credentials=credentials,
            authorization_reference=validated_data.get("authorization_reference"),
            authorization_method=enum.AuthMethodChoices.COMMAND,
            ad_hoc_token=AdhocToken.from_dict(validated_data["token"]),
        )
        logger.info(
            f"Created a {session.status} session for remote start for token_uid: {validated_data['token']['uid']}, auth_reference: {validated_data['token']['authorization_reference']}"
        )
        return session

    def start_session(
        self,
        sender_party: Party,
        credentials: Credentials,
        validated_data: Dict[str, Any],
    ) -> OCPIResponse:
        billed_to = get_credentialsrole(party=sender_party)
        session = self.session_repo.find_session_by_auth_ref_and_token_uid(
            validated_data
        )

        if not session:
            webhook_response = self.send_start_command_webhook(
                billed_to=billed_to,
                validated_data=validated_data,
                command_type=RemoteCommandType.START_SESSION,
            )

            if webhook_response.get("data", {}).get("result") == "ACCEPTED":
                self._create_new_session(credentials, validated_data, billed_to)
            return self.create_ocpi_response(webhook_response, "START")

        if session.status == Session.ACTIVE:
            logger.info(
                f"Found existing active session for remote start for token_uid: {validated_data['token']['uid']}, auth_reference: {validated_data['token']['authorization_reference']}"
            )
            return OCPIResponse(
                None,
                status_message="Cannot start - ACTIVE session",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        if session.status in [Session.PENDING, Session.RESERVATION]:
            logger.info(
                f"Retrying existing {session.status} session for remote start with token_uid: {validated_data['token']['uid']} and auth_reference: {validated_data['token']['authorization_reference']}"
            )
            webhook_response = self.send_start_command_webhook(
                billed_to=billed_to,
                validated_data=validated_data,
                command_type=RemoteCommandType.START_SESSION,
            )
            return self.create_ocpi_response(webhook_response, "START")
        return OCPIResponse(
            None,
            status_message="Cannot start - COMPLETED/INVALID session",
            http_status=status.HTTP_400_BAD_REQUEST,
        )

    @staticmethod
    def _prepare_start_session_payload(
        billed_to: Optional[CredentialsRole],
        validated_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        command_id = (
            validated_data.get("authorization_reference") or generate_random_token()
        )
        token_copy = validated_data["token"].copy

        command_store[command_id] = validated_data
        token_copy["type"] = str(token_copy["type"])
        payload = {
            "response_url": build_absolute_uri(
                reverse("chargepoint-remote-command-result", args=(command_id,))
            ),
            "token": token_copy,
            "authorization_reference": validated_data["authorization_reference"],
            "evse_uid": validated_data.get("evse_uid"),
            "connector_id": validated_data.get("connector_uid"),
        }
        if billed_to:
            payload["billed_to"] = str(billed_to.get_party())

        return payload

    def send_start_command_webhook(
        self,
        billed_to: Optional[CredentialsRole],
        validated_data: Dict[str, Any],
        command_type: RemoteCommandType,
    ) -> Dict[str, Any]:
        webhook = self.webhook_repo.get_remote_command_webhook(command_type)
        if not webhook or not webhook.active:
            raise ValidationError(f"No webhook configured for {command_type}")

        payload = self._prepare_start_session_payload(
            billed_to=billed_to,
            validated_data=validated_data,
        )

        response = self.send_webhook_and_save_event(webhook, payload, command_type)
        return response


class StopCommandServices(RemoteCommandServices):
    def __init__(self):
        super().__init__()
        self.session_repo = SessionRepository()
        self.webhook_repo = WebhookRepository()

    def send_stop_command_webhook(self, payload: dict, command_type: RemoteCommandType):
        webhook = self.webhook_repo.get_remote_command_webhook(command_type)
        if not webhook or not webhook.active:
            raise ValidationError(f"No webhook configured for {command_type}")
        response = self.send_webhook_and_save_event(webhook, payload, command_type)
        return response

    def stop_session(
        self,
        validated_data: Dict[str, Any],
    ) -> OCPIResponse:
        session = self.session_repo.find_session_by_uid(validated_data["uid"])
        if not session:
            logger.warning(
                f"Could not find any session for provided uid: {validated_data['uid']}"
            )
            return OCPIResponse(
                status_message="Session not found",
                status_code=2001,
                http_status=HTTP_200_OK,
            )
        response = self.send_stop_command_webhook(
            payload=validated_data, command_type=RemoteCommandType.STOP_SESSION
        )
        return self.create_ocpi_response(
            response, RemoteCommandType.STOP_SESSION.value()
        )


def process_remote_command(
    request,
    command_serializer,
    webhook_serializer,
    command_prefix,
    extra_actions=None,
):
    """
    Old function - use new services instead
    This is here so existing code doesn't break while we migrate
    """
    logger.warning(
        "process_remote_command is deprecated - use StartSessionService, StopSessionService, etc."
    )

    return OCPIResponse(
        None,
        status_message="This function is deprecated - please use the new service classes",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
