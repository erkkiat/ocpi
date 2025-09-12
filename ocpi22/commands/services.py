from logging import getLogger
from typing import Optional, Dict, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from rest_framework import status

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

from webhooks.services import WebhookEventService
from webhooks.models import WebhookEventType
from rest_framework.reverse import reverse
from ocpi22.util import build_absolute_uri, generate_random_token
from ocpi22.tokens.util import get_token_id
from ocpi22.tokens.util import get_token_type
from ocpi22.choices import TokenType
from webhooks.models import WebhookEvent
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.sessions.util import create_session
from ocpi22.models import enum
from ocpi22.cpo.api import close_active_sessions_for_evse
from django.utils.timezone import now

from ocpiconnector.party import Party

import requests

logger = getLogger(__name__)


class InvalidSenderPartyError(Exception):
    pass


def get_validated_sender_party(request_meta: Dict[str, Any]) -> Party | None:
    sender_party = get_sender_party(request_meta)

    if not isinstance(sender_party, Party) and len(str(sender_party)) != 6:
        raise InvalidSenderPartyError(
            f"Sender party must be a Party object, got: {type(sender_party)}"
        )
    return sender_party


class StartSessionService:
    def __init__(self):
        self.webhook_repository = WebhookRepository()

    def start_session(
        self,
        sender_party: Party,
        ocpi_party: CredentialsRole,
        credentials: Credentials,
        validated_data: Dict[str, Any],
    ) -> OCPIResponse:
        billed_to = get_credentialsrole(party=sender_party)
        session = self._find_existing_session(validated_data)

        if session and session.status == Session.COMPLETED:
            return OCPIResponse(
                None,
                status_message="Cannot start - session is already completed",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        webhook_response = self.send_command_webhook(
            ocpi_party=ocpi_party,
            billed_to=billed_to,
            session=session,
            validated_data=validated_data,
            command_type=RemoteCommandType.START_SESSION,
        )

        if webhook_response.get("result") == "ACCEPTED":
            self._handle_successful_start(
                credentials=credentials,
                session=session,
                validated_data=validated_data,
                billed_to=billed_to,
            )

        return self._create_ocpi_response(webhook_response, "START")

    @staticmethod
    def _find_existing_session(validated_data: Dict[str, Any]) -> Optional[Session]:
        auth_ref = validated_data.get("authorization_reference")
        session_id = validated_data.get("session_id")

        if auth_ref:
            return Session.objects.filter(authorization_reference=auth_ref).first()
        elif session_id:
            return Session.objects.filter(uid=session_id).first()

        return None

    def send_command_webhook(
        self,
        ocpi_party: CredentialsRole,
        billed_to: Optional[CredentialsRole],
        session: Optional[Session],
        validated_data: Dict[str, Any],
        command_type: RemoteCommandType,
    ) -> Dict[str, Any]:
        """Send webhook command and return response."""
        if settings.PERFORMANCE_TEST or settings.CPO_SIMULATOR:
            return {"timeout": 90, "result": "ACCEPTED"}

        webhook = self.webhook_repository.get_remote_command_webhook(command_type)
        if not webhook or not webhook.active:
            raise ValidationError(f"No webhook configured for {command_type}")

        payload = self._prepare_payload(
            ocpi_party=ocpi_party,
            billed_to=billed_to,
            session=session,
            validated_data=validated_data,
        )

        return self._send_webhook_and_save_event(webhook, payload, command_type)

    @staticmethod
    def _prepare_payload(
        ocpi_party: CredentialsRole,
        billed_to: Optional[CredentialsRole],
        session: Optional[Session],
        validated_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        command_id = (
            validated_data.get("authorization_reference") or generate_random_token()
        )
        token = validated_data.get("token", {})

        if billed_to and "billed_to" not in token:
            token["billed_to"] = str(billed_to.get_party())
        if billed_to and "ocpi_master" not in token:
            token["ocpi_master"] = str(billed_to.get_party())

        command_store[command_id] = validated_data

        # Get token_type and ensure it's a string
        token_type_value = (
            session.cdr_token.token_type
            if session
            else get_token_type(token, TokenType.APP_USER)
        )

        payload = {
            "response_url": build_absolute_uri(
                reverse("chargepoint-remote-command-result", args=(command_id,))
            ),
            "token_id": session.cdr_token.uid if session else get_token_id(token),
            "token_type": str(token_type_value),
            "authorization_reference": (
                session.authorization_reference
                if session
                else validated_data.get("authorization_reference")
            ),
            "auth_method": str(enum.AuthMethodChoices.COMMAND),
            "from_party": ocpi_party.party_str(),
            "evse_id": session.evse.uid if session else validated_data.get("evse_uid"),
            "connector_id": session.connector.uid
            if session
            else validated_data.get("connector_id"),
        }
        if billed_to:
            payload["billed_to"] = str(billed_to.get_party())

        return payload

    @staticmethod
    def _create_webhook_event_safe(webhook, event_type, payload):
        return WebhookEvent.objects.create(
            webhook=webhook, event_type=event_type, payload=payload
        )

    def _send_webhook_and_save_event(self, webhook, payload, command_type):
        event_type_mapping = {
            RemoteCommandType.START_SESSION: WebhookEventType.REMOTE_START_REQUESTED,
            RemoteCommandType.STOP_SESSION: WebhookEventType.REMOTE_STOP_REQUESTED,
        }

        if command_type in event_type_mapping:
            event_type = event_type_mapping[command_type]

            event = WebhookEventService.create_event(
                webhook=webhook, event_type=event_type, payload=payload
            )
        else:
            event_type = f"remote_command.{command_type.lower()}_requested"
            event = self._create_webhook_event_safe(webhook, event_type, payload)

        WebhookEventService.mark_attempt_started(event)

        try:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                **webhook.get_auth_headers(),
            }

            response = requests.post(
                webhook.url,
                json=payload,
                headers=headers,
                timeout=webhook.timeout_seconds,
            )

            if response.status_code < 400:
                WebhookEventService.mark_success(
                    event, status_code=response.status_code
                )

                try:
                    return response.json()
                except (ValueError, TypeError):
                    return {"timeout": 90, "result": "ACCEPTED"}
            else:
                error = f"HTTP {response.status_code}: {response.text[:100]}"
                WebhookEventService.mark_failed(event, error, response.status_code)
                raise

        except requests.exceptions.RequestException as e:
            WebhookEventService.mark_failed(event, f"Request failed: {str(e)}")
            raise

    def _handle_successful_start(
        self,
        credentials: Credentials,
        session: Optional[Session],
        validated_data: Dict[str, Any],
        billed_to: CredentialsRole,
    ):
        """Handle successful webhook response by updating or creating session."""
        if not session:
            session = self._create_new_session(credentials, validated_data, billed_to)
            logger.info(f"Created new session {session.uid}")
        else:
            logger.info(f"Found existing session {session.uid}")

        session.start_date_time = now()
        session.save(update_fields=["start_date_time"])

        if settings.CPO_SIMULATOR:
            from ocpi22.commands.cpo_simulator import start_simulated_session

            start_simulated_session(session, **validated_data)

    @staticmethod
    def _create_new_session(
        credentials: Credentials,
        validated_data: Dict[str, Any],
        billed_to: CredentialsRole,
    ) -> Session:
        """Create a new charging session."""
        session_data = validated_data.copy()
        evse_uid = validated_data.get("evse_uid")
        connector_id = validated_data.get("connector_id")

        session_data.update(
            {
                "ad_hoc_token": AdhocToken.from_dict(validated_data.get("token")),
                "billed_to": billed_to.get_party(),
                "authorization_method": enum.AuthMethodChoices.COMMAND,
                "credentials": credentials,
                "connector_id": connector_id,
            }
        )
        session_data.pop("token")  # Remove token, we converted it

        close_active_sessions_for_evse(evse_uid)
        return create_session(**session_data)

    @staticmethod
    def _create_ocpi_response(webhook_response, command_name):
        timeout = webhook_response.get("timeout", 60)
        result = webhook_response.get("result", "REJECTED").upper()

        message = MessageTexts.get(
            f"{command_name}_{result}",  # e.g., "START_ACCEPTED"
            MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT", "Command processed"),
        )

        if result == "ACCEPTED":
            ocpi_status = Ocpi.OK
            http_status = status.HTTP_200_OK
        else:
            ocpi_status = 2000
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

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


class StopSessionService:
    def __init__(self):
        self.webhook_repository = WebhookRepository()

    def stop_session(
        self,
        sender_party: Party,
        ocpi_party: CredentialsRole,
        credentials: Credentials,
        validated_data: Dict[str, Any],
    ) -> OCPIResponse:
        session_id = validated_data.get("session_id")
        session = Session.objects.filter(uid=session_id).first()

        if not session:
            return OCPIResponse(
                None,
                status_message="Session not found",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        if session.status == Session.COMPLETED:
            return OCPIResponse(
                None,
                status_message="Session is already completed",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        billed_to = get_credentialsrole(party=sender_party)
        start_service = StartSessionService()
        try:
            webhook_response = start_service.send_command_webhook(
                ocpi_party=ocpi_party,
                billed_to=billed_to,
                session=session,
                validated_data=validated_data,
                command_type=RemoteCommandType.STOP_SESSION,
            )
        except Exception as e:
            return OCPIResponse(
                None,
                status_message=f"Could not communicate with charger system: {str(e)}",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if webhook_response.get("result") == "ACCEPTED":
            self._complete_session(session)

        return self._create_ocpi_response(webhook_response, "STOP")

    @staticmethod
    def _create_ocpi_response(webhook_response, command_name):
        timeout = webhook_response.get("timeout", 60)
        result = webhook_response.get("result", "REJECTED").upper()

        message = MessageTexts.get(
            f"{command_name}_{result}",  # e.g., "STOP_ACCEPTED"
            MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT", "Command processed"),
        )

        if result == "ACCEPTED":
            ocpi_status = Ocpi.OK
            http_status = status.HTTP_200_OK
        else:
            ocpi_status = 2000
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

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

    def _complete_session(self, session):
        session.status = Session.COMPLETED
        session.end_date_time = now()
        session.save(update_fields=["status", "end_date_time"])
        session.send_updates()


class ReserveNowService:
    def __init__(self):
        self.webhook_repository = WebhookRepository()

    def reserve_now(
        self,
        sender_party: Party,
        ocpi_party: CredentialsRole,
        credentials: Credentials,
        validated_data: Dict[str, Any],
    ) -> OCPIResponse:
        start_service = StartSessionService()

        try:
            webhook_response = start_service.send_command_webhook(
                ocpi_party=ocpi_party,
                billed_to=None,  # Will be calculated if needed
                session=None,
                validated_data=validated_data,
                command_type=RemoteCommandType.RESERVE_NOW,
            )
        except Exception as e:
            return OCPIResponse(
                None,
                status_message=f"Could not communicate with charger system: {str(e)}",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if webhook_response.get("result") == "ACCEPTED":
            # Use the already calculated billed_to from the passed sender_party
            billed_to = get_credentialsrole(party=sender_party)
            session = start_service._create_new_session(
                credentials, validated_data, billed_to
            )
            logger.info(f"Created reservation session {session.uid}")

        return start_service._create_ocpi_response(webhook_response, "RESERVE")


def fill_msp_information(token: dict, billed_to):
    if "billed_to" not in token:
        token["billed_to"] = billed_to.get_party()
    if "ocpi_master" not in token:
        token["ocpi_master"] = billed_to
    return token


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
