import json
import time
from logging import getLogger
from typing import Union
from urllib.parse import urljoin

import aiohttp
import asyncio

from aiohttp import ClientError
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from rest_framework import status

from ocpi22.choices import (
    OcpiRolesEnum,
    AuthorizationEnum,
)
from ocpi22.cpo.repositories import CredentialsRepository
from ocpi22.credentials.services import CredentialsService
from ocpi22.models import enum
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Location
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.headers import make_headers
from ocpi22.ssl_services import load_ssl_context
from ocpi22.tasks import get_cert_from_env
from ocpi22.tokens.util import get_token_id
from ocpiconnector.ocpi_identities import get_our_party
from ocpiconnector.party import Party
from util import with_trailing_slash

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
    status_code, json_data, ocpi_master = successful_task.result()
    if status_code != 200:
        return None
    if isinstance(json_data, dict):
        json_data = json_data.get("data")
        if isinstance(json_data, dict) and json_data.get("allowed"):
            json_data["responding_party"] = successful_task.get_name()
            token = json_data.get("token", {})
            json_data["msp"] = (
                f'{token.get("country_code", "")}*{token.get("party_id", "")}'
            )
            return json_data
        pass
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


async def authorize_with_msps(token: Union[str, Token], data, parties):
    """
    Send authorization request asynchronously to all MSPs and wait for the first ALLOWED response.
    If no MSP allows the token, returns the first denial response with specific reason.

    @param token: token_id as str or Token object
    @param data: the data to be sent in the Token authorization request
    @param parties: [(url, token_base64, country_code, party_id, credentials)]
    @return: dict with authorization response or None if all tasks fail
    """
    from integrations.hubject.services import HubjectService

    def make_url(base_url, token_id_param):
        return urljoin(with_trailing_slash(base_url), f"{token_id_param}/authorize")

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

    sender = get_our_party(OcpiRolesEnum.CPO)
    token_id = get_token_id(token)

    # Prepare SSL contexts and roles
    ssl_contexts = await asyncio.gather(
        *[create_ssl_context(credentials.id) for _, _, _, _, credentials in parties]
    )
    prefetched_roles = await prefetch_roles()

    allowed_response = None
    first_denial_response = None

    async with aiohttp.ClientSession() as session:
        # Create authorization tasks for all MSPs
        tasks = [
            asyncio.create_task(
                post_request(
                    session=session,
                    ssl_context=ssl_context,
                    url=make_url(url, token_id),
                    data=data,
                    ocpi_master=role,
                    headers=make_headers(
                        token_base64, to=Party(country_code, party_id), sender=sender
                    ),
                ),
                name=f"{country_code}*{party_id}",
            )
            for (
                url,
                token_base64,
                country_code,
                party_id,
                _,
            ), ssl_context, role in zip(parties, ssl_contexts, prefetched_roles)
        ]

        # Add Hubject task if enabled
        if settings.ENABLE_HUBJECT:
            role = await sync_to_async(
                CredentialsRepository.find_hubject_credentials_role,
                thread_sensitive=True,
            )()
            if role and CredentialsService.is_location_allowed(
                role.credentials, data.get("location_id", "")
            ):
                tasks.append(
                    asyncio.create_task(
                        HubjectService.post_authorize_request(
                            operator_id=str(sender),
                            token_id=token_id,
                        ),
                        name=settings.HUBJECT_OPERATOR_ID,
                    )
                )

        remaining_tasks = set(tasks)

        while remaining_tasks:
            done_tasks, pending_tasks = await asyncio.wait(
                remaining_tasks, return_when=asyncio.FIRST_COMPLETED
            )

            for task in done_tasks:
                try:
                    response_data = process_task_result(task)
                    if not response_data:
                        continue

                    if response_data.get("allowed") == AuthorizationEnum.ALLOWED:
                        allowed_response = response_data
                        break
                    elif first_denial_response is None:
                        first_denial_response = response_data
                except Exception:
                    logger.exception(f"Task {task.get_name()} failed")

            if allowed_response:
                break

            remaining_tasks = pending_tasks

        for task in remaining_tasks:
            if not task.done():
                logger.debug(f"Cancelling task {task.get_name()}")
                task.cancel()

    return allowed_response or first_denial_response


def authorize_with_msps_sync(token: str, location: Location, parties: list[tuple]):
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

    # Todo: Add info texts for TokenNotAuthorized
    TokenNotAuthorized = TokenAuthorization(
        allowed=AuthorizationEnum.NOT_ALLOWED,
        token=AdhocToken(
            valid=False, type="", uid=token, billed_to=Party(), ocpi_master=None
        ),
    )

    # Todo: Try authorizing through direct connections first, they may be cheaper than hub connections

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
    logger.info(f"Authorizing token {token} with MSPs {', '.join(formatted_parties)}")

    response = asyncio.run(authorize_with_msps(token, data, parties))
    if response:
        responding_party = response.get(
            "responding_party", ""
        )  # See response.token to see who is actually paying the bill
        if not response:
            return TokenNotAuthorized
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
                    'Cannot create TokenAuthorization from response from '
                    f'{serializer.validated_data.get("responding_party", "N/A")}: {serializer.errors}'
                )
                return TokenNotAuthorized
        except TypeError:
            logger.exception("Cannot create TokenAuthorization from response")
            return TokenNotAuthorized
    return TokenNotAuthorized
