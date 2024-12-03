import json
from logging import getLogger
from typing import Union
from urllib.parse import urljoin

import aiohttp
import asyncio

from asgiref.sync import sync_to_async


from ocpi22.choices import (
    OcpiRolesEnum,
    OcpiModuleEnum,
    AuthorizationEnum,
    EndpointRoleEnum,
)
from ocpi22.credentials.util import find_endpoints_by_roles
from ocpi22.models import enum
from ocpi22.models.location import Location
from ocpi22.models.token import Token
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.ocpi.headers import make_headers
from ocpi22.tokens.util import get_token_id
from ocpiconnector.ocpi_identities import get_our_party
from ocpiconnector.party import Party
from util import with_trailing_slash

from typing import TYPE_CHECKING

logger = getLogger(__name__)

if TYPE_CHECKING:
    ...


async def post_request(session, url, data, ocpi_master, headers=None) -> (int, dict):
    headers = headers or {}
    headers.update({"Content-Type": "application/json", "Accept:": "application/json"})
    async with session.post(url, json=data, headers=headers) as response:
        status = response.status
        try:
            json_data = await response.json()
        except (aiohttp.ContentTypeError, json.JSONDecodeError):
            logger.error(f"Cannot decode JSON response from url {url}")
            json_data = None

        return status, json_data, ocpi_master


def process_task_result(successful_task):
    # print(f"Response from {successful_task.get_name()} len: {len(successful_task.result())}")
    try:
        status_code, json_data, ocpi_master = successful_task.result()
        if status_code != 200:
            return None
        if isinstance(json_data, dict):
            json_data = json_data.get("data")
            # If content is a Token authorize response, then break, otherwise continue
            if isinstance(json_data, dict) and json_data.get("allowed"):
                logger.info(f"Received authorization from {successful_task.get_name()}")
                json_data["responding_party"] = successful_task.get_name()
                json_data["ocpi_master"] = ocpi_master
                return json_data
    except (aiohttp.ContentTypeError, json.JSONDecodeError):
        # Handle the case where response is not JSON or cannot be decoded
        logger.error(
            f"Cannot decode JSON response from party {successful_task.get_name()}"
        )
        pass
    return None


async def authorize_with_msps(token: Union[str, Token], data, parties):
    """
    Send authorization request asynchronously to all MSPs and wait for the first properly formatted response.

    @param token: token_id as str or Token object
    @param data: the data to be sent in the Token authorization request
    @param parties: [(url, token_base64, country_code, party_id, credentials)]
    @return:
    """

    def make_url(base_url, token_id_param):
        return urljoin(with_trailing_slash(base_url), f"{token_id_param}/authorize")

    result = None
    pending_tasks = []
    sender = get_our_party(OcpiRolesEnum.CPO)
    token_id = get_token_id(token)
    # (endpoint.url, credentials.theirs_base64(), country_code, party_id, credentials)

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(
                post_request(
                    session=session,
                    url=make_url(url, token_id),
                    data=data,
                    ocpi_master=await sync_to_async(credentials.get_role)(
                        Party(country_code, party_id)
                    ),
                    headers=make_headers(
                        token_base64, to=Party(country_code, party_id), sender=sender
                    ),
                ),
                name=str(Party(country_code, party_id)),
            )
            for url, token_base64, country_code, party_id, credentials in parties
        ]

        while tasks:
            done_tasks, pending_tasks = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            # print(f'Processing {len(done_tasks)} done_tasks tasks ({len(pending_tasks)} still pending_tasks)...')

            for task in done_tasks:
                try:
                    result = process_task_result(task)
                    if result:
                        break
                except Exception:
                    logger.exception(f"Task {task.get_name()} failed")

            if not pending_tasks:
                # No more tasks pending_tasks, break the loop
                return result

            tasks = set(pending_tasks)

        # Cancel all pending_tasks tasks as we have found our successful task or there are no tasks left
        for task in pending_tasks:
            logger.info(f"Cancelling task {task.get_name()}", task.cancel())

        return result


def authorize_with_msps_sync(
    token: str, location: Location = None, parties: list[tuple] = None
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

    # Todo: Add info texts for TokenNotAuthorized
    TokenNotAuthorized = TokenAuthorization(
        allowed=AuthorizationEnum.NOT_ALLOWED,
        token=AdhocToken(
            valid=False, type="", uid=token, billed_to=Party(), ocpi_master=None
        ),
    )

    # Todo: Try authorizing through direct connections first, they may be cheaper than hub connections

    if not parties:
        parties = find_endpoints_by_roles(
            (OcpiRolesEnum.EMSP.value, OcpiRolesEnum.HUB.value),
            OcpiModuleEnum.TOKENS,
            endpoint_role=EndpointRoleEnum.SENDER.value,
        )

    data = (
        {
            "location_id": location.uid,
            "evse_uids": [e.uid for e in location.evses.all()],
        }
        if location
        else {}
    )

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
                ocpi_master = response.get("ocpi_master")
                token["ocpi_master"] = ocpi_master
                token["billed_to"] = ocpi_master
                return TokenAuthorization(
                    **serializer.validated_data,
                    token=AdhocToken(**token),
                    responding_party=responding_party,
                    auth_method=enum.AuthMethodChoices.AUTH_REQUEST,
                    billed_to=ocpi_master.get_party(),
                    ocpi_master=ocpi_master,
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
