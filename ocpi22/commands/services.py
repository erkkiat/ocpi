from logging import getLogger

from django.conf import settings
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.reverse import reverse

from ocpi22.choices import TokenType, MessageTexts
from ocpi22.commands.serializers import CommandResponse
from ocpi22.models import enum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import Ocpi, OCPIResponse, options_message
from ocpi22.tokens.util import get_token_id, get_token_type
from ocpi22.util import generate_random_token, command_store, build_absolute_uri
from ocpi22.webhooks import send_to_webhook
from ocpiconnector.party import Party

logger = getLogger(__name__)


def get_sender_party(request) -> Party:
    billed_to = get_sender_party(request.META)
    assert isinstance(billed_to, Party) and len(str(billed_to)) == 6, (
        f"Billed_to needs to be set with party ID: {billed_to}."
        f" (You need to be using Credentials and OCPI routing headers for the connection.)"
    )
    return billed_to


def process_remote_command(
    self,
    request,
    command_serializer,
    webhook_serializer,
    command_prefix,
    extra_actions=None,
):
    if not getattr(request, "data", None):
        return OCPIResponse(
            {"status_message": options_message}, status=status.HTTP_400_BAD_REQUEST
        )
    billed_to = get_credentialsrole(party=self.get_sender_party(request))
    serializer = command_serializer(
        data=request.data, context={"request": request, "version": request.version}
    )
    if serializer.is_valid():
        token = serializer.validated_data.get("token", "")
        token = fill_msp_information(token, billed_to)
        authorization_reference = serializer.validated_data.get(
            "authorization_reference"
        )
        session_id = serializer.validated_data.get("session_id")

        session: Session = Session.get_if_exists(
            Q(authorization_reference=authorization_reference)
            | Q(cdr_token__uid=token)
            | Q(uid=session_id)
        )

        if session and session.status == Session.COMPLETED:
            raise APIException(
                f"Unable to complete command {command_prefix} "
                "because the session has already been completed."
            )

        ocpi_response_url = serializer.validated_data.pop("response_url")
        token_uid = session.cdr_token.uid if session else get_token_id(token)
        evse_uid = (
            session.evse.uid if session else serializer.validated_data.get("evse_uid")
        )
        connector_id = (
            session.connector.uid
            if session
            else serializer.validated_data.get("connector_id")
        )

        # Store the command for use during the next {settings.REMOTE_COMMAND_EXPIRATION} seconds
        command_id = authorization_reference or generate_random_token()
        command_store[command_id] = serializer.validated_data

        # The worst scenario is this
        ocpi_status = 2000
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        timeout = 60
        status_message = ""
        ocpi_result = CommandResponse.REJECTED

        # Prepare the command for CPO management system
        initial_data = dict(
            response_url=build_absolute_uri(
                reverse("chargepoint-remote-command-result", args=(command_id,))
            ),
            token_id=token_uid,
            token_type=session.cdr_token.token_type
            if session
            else get_token_type(token, TokenType.APP_USER),
            authorization_reference=session.authorization_reference
            if session
            else authorization_reference,
            auth_method=enum.AuthMethodChoices.COMMAND,
            from_party=request.ocpi_party.party_str(),  # HUB or eMSP
            evse_id=evse_uid,
            connector_id=connector_id,
            billed_to=billed_to,
        )
        initial_data.update(**serializer.validated_data)

        if settings.PERFORMANCE_TEST or settings.CPO_SIMULATOR:
            data = dict(timeout=90, result="ACCEPTED")
        else:
            data = send_to_webhook(initial_data, webhook_serializer)
        if not data:
            logger.error(
                f"Unable to connect to CPMS webhook at {webhook_serializer.URL}."
            )
            return OCPIResponse(
                None,
                status_message=f"Unable to complete {command_prefix} "
                "due to a communication error.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                status_code=Ocpi.ServerError.GENERIC_SERVER_ERROR,
            )

        timeout = int(data.get("timeout", timeout))
        result = data.get("result", CommandResponse.REJECTED).upper()
        logger.info(f"Result from charger for command {command_prefix}: {result}")
        message = MessageTexts.get(
            f"{command_prefix}_{result}",  # E.g. try to get response message for START_<result>
            MessageTexts.get(
                result,  # Then just for <result>
                MessageTexts.get("DEFAULT_CHARGER_ERROR_TEXT"),
            ),
        )  # Or just use the default
        if result == CommandResponse.ACCEPTED:
            if extra_actions:
                extra_actions(
                    request,
                    session,
                    ocpi_response_url=ocpi_response_url,
                    serializer=serializer,
                    **initial_data,
                )

            ocpi_result = CommandResponse.ACCEPTED
            ocpi_status = Ocpi.OK
            http_status = status.HTTP_200_OK

        response_serializer = CommandResponse(
            data=dict(result=ocpi_result, timeout=timeout, message=message)
        )
        assert response_serializer.is_valid(), f"Internal error, CommandResponse is not properly formatted: {response_serializer.errors}"
        return OCPIResponse(
            response_serializer.data,
            status_code=ocpi_status,
            http_status=http_status,
            status_message=status_message,
        )
    else:
        return OCPIResponse(
            serializer.errors,
            status_message="Please check your request parameters",
            http_status=status.HTTP_400_BAD_REQUEST,
            status_code=Ocpi.ClientError.INVALID_OR_MISSING_PARAMETERS,
        )


def fill_msp_information(token: dict, billed_to: CredentialsRole) -> dict:
    if "billed_to" not in token:
        token["billed_to"] = billed_to.get_party()
    if "ocpi_master" not in token:
        token["ocpi_master"] = billed_to
    return token
