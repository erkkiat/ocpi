import json
import time
from logging import getLogger

import aiohttp
import asyncio

from aiohttp import ClientError
from asgiref.sync import sync_to_async
from django.db import close_old_connections
from rest_framework import status

from ocpi22.choices import (
    AuthorizationEnum,
)
from ocpi22.models import enum
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ssl_services import load_ssl_context
from ocpi22.tasks import get_cert_from_env
from ocpi22.tokens.dataclasses import TokenDto
from ocpi22.tokens.services import TokenAuthorizationService
from ocpiconnector.party import Party

from typing import TYPE_CHECKING

logger = getLogger(__name__)

if TYPE_CHECKING:
    ...


async def post_request(
    session, url, data, ocpi_master, headers=None, ssl_context=None
) -> (int, dict):
    headers = headers or {}
    response_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    headers.update({"Content-Type": "application/json", "Accept": "application/json"})

    start_time = time.time()
    try:
        response = await session.post(
            url, json=data, headers=headers, ssl=ssl_context, timeout=8
        )
        duration = time.time() - start_time
        response_status = response.status
        json_data = await response.json()
    except (aiohttp.ContentTypeError, json.JSONDecodeError):
        duration = time.time() - start_time
        logger.exception(
            f"Cannot decode JSON response from url {url}",
            extra={"response_duration": duration, "status_code": response_status},
        )
        json_data = None
    except ClientError:
        duration = time.time() - start_time
        logger.exception(
            f"Cannot connect to {url} for token authorization",
            extra={"response_duration": duration},
        )
        return 0, None, None

    logger.info(
        "Received authorization from %s with status : %s",
        url,
        response_status,
        extra={**json_data, "response_duration": duration}
        if json_data
        else {"response_duration": duration},
    )
    return response_status, json_data, ocpi_master


def process_task_result(successful_task) -> dict | None:
    try:
        status_code, json_data, ocpi_master = successful_task.result()
    except (TimeoutError, asyncio.TimeoutError) as e:
        logger.warning(f"Authorization task failed with exception: {e}")
        return None

    if status_code != 200:
        logger.warning(
            f"Authorization failed with status {status_code}, data: {json_data} for {str(ocpi_master)}"
        )
        return None

    if not isinstance(json_data, dict):
        return None

    response_data = json_data.get("data")
    task_name = successful_task.get_name()
    status_code = json_data.get("status_code")
    if not response_data and isinstance(status_code, int) and status_code >= 2000:
        logger.warning(
            f"{task_name} responded OCPI error {json_data.get('status_message')}"
        )
        return {
            "allowed": "NOT_ALLOWED",
        }
    if isinstance(response_data, dict) and response_data.get("allowed"):
        response_data["responding_party"] = task_name
        token = response_data.get("token", {})
        response_data["msp"] = (
            f"{token.get('country_code', '')}*{token.get('party_id', '')}"
        )
        return response_data
    return None


def _get_credentials_by_id(credential_id):
    close_old_connections()
    return Credentials.objects.filter(id=credential_id).first()


async def create_ssl_context(credential_id):
    logger.info(f"Creating SSL context for credentials {credential_id}")
    credentials = await sync_to_async(_get_credentials_by_id, thread_sensitive=True)(
        credential_id
    )

    if not credentials:
        logger.warning(
            f"No credentials found for {credential_id}, skipping ssl context creation"
        )
        return None

    ca_cert = get_cert_from_env(credentials.ca_certificate_name)
    private_key = get_cert_from_env(credentials.private_key_name)
    client_cert = get_cert_from_env(credentials.client_certificate_name)

    return load_ssl_context(
        client_cert=client_cert, private_key=private_key, ca_cert=ca_cert
    )


async def authorize_with_msps(token_dto: TokenDto, data: dict, parties: list[tuple]):
    """
    Send authorization request asynchronously to all MSPs and wait for the
    first ALLOWED response in the adhoc token case. Whenever the token is known, only
    send the request to the MSP that issued the token.
    If no MSP allows the token, returns the first denial response with specific reason.

    @param token: TokenDto representing the token and metadata
    @param data: the data to be sent in the Token authorization request
    @param parties: [(url, token_base64, country_code, party_id, credentials)]
    @return: dict with authorization response or None if all tasks fail
    """

    async def prefetch_roles():
        """Prefetch credential roles before async operations."""
        roles = []
        for _, _, country_code, party_id, credentials in parties:
            role = await sync_to_async(
                lambda creds, cc, pid: creds.roles.filter(
                    country_code__iexact=cc, party_id__iexact=pid
                ).first(),
                thread_sensitive=True,
            )(credentials, country_code, party_id)
            roles.append(role)
        return roles

    # Prepare SSL contexts and roles
    ssl_contexts = await asyncio.gather(
        *[create_ssl_context(credentials.id) for _, _, _, _, credentials in parties]
    )
    prefetched_roles = await prefetch_roles()

    token_uid = token_dto.uid
    service = TokenAuthorizationService()
    party_details = service.build_party_details(
        parties, ssl_contexts, prefetched_roles, token_uid
    )
    if token_dto.adhoc:
        return await service.authorize_adhoc_token(party_details, data, token_uid)

    else:
        party_details = [
            p for p in party_details if p.ocpi_master == token_dto.token.ocpi_master
        ]
        return await service.authorize_known_token(party_details, data, token_uid)


def authorize_with_msps_sync(
    token_dto: TokenDto, parties: list[tuple], location: Location = None
):
    """
    When a Token ID is not known, we need to authorize with all MSPs we have a contract with.
    This sync function calls an async function to process authorizations in parallel.
    Defaults to a list of all MSPs, but typically a list of one is also useful.

    @param token: An unknown Token ID to be authorized
    @param location: An optional Location for which the charging is requested, this may be relevant for the MSP
    @param parties: An optional tuple of parties to which the authorization request should be sent
    @return: TokenAuthorization or None
    """
    from ocpi22.tokens.auth import TokenAuthorization
    from ocpi22.ocpi.serializers import AuthorizationInfoSerializer

    token_uid = token_dto.uid

    # Todo: Add info texts for TokenNotAuthorized
    TokenNotAuthorized = TokenAuthorization(
        allowed=AuthorizationEnum.NOT_ALLOWED,
        token=AdhocToken(
            valid=False, type="", uid=token_uid, billed_to=Party(), ocpi_master=None
        ),
    )
    data = (
        {
            "location_id": location.uid,
            "evse_uids": [e.uid for e in location.evses.all()],
        }
        if location
        else {}
    )

    formatted_parties = [
        f"{country_code}*{party_id}: {url}"
        for url, _token_base64, country_code, party_id, _credentials in parties
    ]
    logger.info(
        f"Authorizing token {token_uid} with MSPs {', '.join(formatted_parties)}"
    )

    response = asyncio.run(authorize_with_msps(token_dto, data, parties))
    if not response:
        return TokenNotAuthorized

    if response.get("allowed") != AuthorizationEnum.ALLOWED:
        logger.info(
            f"Token {token_uid} not authorized by {response.get('responding_party', 'N/A')}",
            extra={"response": response},
        )
        return TokenNotAuthorized

    responding_party = response.get("responding_party", "")
    try:
        serializer = AuthorizationInfoSerializer(data=response)
        if serializer.is_valid():
            token = serializer.validated_data.pop("token", {})
            msp = response.get("msp")
            token["billed_to"] = msp
            token["ocpi_master"] = msp
            return TokenAuthorization(
                **serializer.validated_data,
                token=AdhocToken(**token),
                responding_party=responding_party,
                auth_method=enum.AuthMethodChoices.AUTH_REQUEST,
                billed_to=Party.from_str(msp),
                msp=msp,
            )
        else:
            logger.error(
                "Cannot create TokenAuthorization from ALLOWED response from %s",
                responding_party or "N/A",
                extra={
                    "response_data": response,
                    "validation_errors": serializer.errors,
                    "responding_party": responding_party,
                },
            )
            return TokenNotAuthorized
    except TypeError:
        logger.exception("Cannot create TokenAuthorization from ALLOWED response")
        return TokenNotAuthorized
