import types
from functools import wraps
from typing import Union

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.credentials import CredentialsRole
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.ocpi.util import OCPIBadRequestResponse, OCPINotOwnerResponse
from ocpi22.ocpi.util_party import get_sender_party, get_to_party
from ocpi22.util import matching_operator
from ocpiconnector.party import Party


def resolve_sender_identity(
    country_code: str,
    party_id: str,
    payload: dict,
    sender_party: "Party",
    ocpi_party=None,
) -> tuple[str, str]:
    """
    Resolve the (country_code, party_id) identity of the sender.

    Priority for PTP senders (who may omit OCPI routing headers entirely):
      1. URL kwargs
      2. OCPI routing headers (sender_party)
      3. Authenticated CredentialsRole (ocpi_party) — PTP fallback

    Priority for all other senders:
      1. URL kwargs
      2. Request body data
      3. OCPI routing headers (sender_party)
    """
    sender_is_ptp = ocpi_party is not None and ocpi_party.role == OcpiRolesEnum.PTP

    if sender_is_ptp:
        country_code = (
            country_code or sender_party.country_code or ocpi_party.country_code
        )
        party_id = party_id or sender_party.party_id or ocpi_party.party_id
    else:
        country_code = country_code or payload.get(
            "country_code", sender_party.country_code
        )
        party_id = party_id or payload.get("party_id", sender_party.party_id)

    return country_code, party_id


def certify_check_ocpi_headers(headers):
    # Todo: add the X-identifier checks
    sender_party = get_sender_party(headers)
    to_party = get_to_party(headers)
    return sender_party and to_party


def requires_sender_role(roles: Union[OcpiRolesEnum, list[OcpiRolesEnum]] = None):
    """
    Decorator to check if the sender has the required role(s) for the given request.
    Fills out the credentialsrole and credentials attributes of the request.
    The CredentialsRole is chosen based on
    the country_code and party_id in the request data or URL and only roles included in
    the original sender's Credentials are possible. If the request is made by a superuser or a hub,
    any CredentialsRole is available.

    @param roles: The required role(s) for the request
    @return: The decorated function
    """
    if not isinstance(roles, list):
        roles = [roles]

    @wraps(requires_sender_role)
    def decorator(func, *_args, **_kwargs):
        assert isinstance(func, types.FunctionType), (
            "This decorator can only be used on functions, not a "
            f"{type(func)} named {func.__name__}."
        )

        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            if "credentialsrole" in kwargs and kwargs["credentialsrole"]:
                raise ImproperlyConfigured(
                    "The decorator @requires_sender_role should be before @requires_credentialsrole"
                )
            assert isinstance(
                kwargs, dict
            ), f"kwargs should be a dict, not a {type(kwargs)}."
            data = kwargs.get("data") or {}
            if not data and hasattr(request, "data") and request.data:
                data = request.data
            # if require_data and (not data or not isinstance(data, dict)):
            #     return OCPIBadRequestResponse('Data is required in the request body.')
            if data:
                data = data.get("data", data) or {}
            headers = getattr(request, "headers", None) or getattr(
                request, "META", None
            )
            sender_party = get_sender_party(headers)

            if request:
                setattr(
                    request,
                    "party_specified_in_url",
                    bool(kwargs.get("country_code") and kwargs.get("party_id")),
                )

            country_code, party_id = resolve_sender_identity(
                country_code=kwargs.get("country_code"),
                party_id=kwargs.get("party_id"),
                payload=data,
                sender_party=sender_party,
                ocpi_party=getattr(request, "ocpi_party", None),
            )
            if not country_code or not party_id:
                return OCPIBadRequestResponse("Country code and party ID are required")
            if request.user.is_superuser or (
                hasattr(request, "credentials")
                and getattr(request.credentials, "is_hub", None)
            ):
                # Pick the right credentialsrole for the almighty
                request.credentialsrole = get_credentialsrole(
                    credentials=None, party=Party(country_code, party_id), create=True
                )
                # Don't overwrite existing credentials
                if not hasattr(request, "credentials") or not request.credentials:
                    request.credentials = request.credentialsrole.credentials
            else:
                # This is a regular OCPI connection, so we need to check the credentials
                criteria = Q(
                    country_code__iexact=country_code, party_id__iexact=party_id
                )
                if roles:  # A specific role is required
                    criteria &= Q(role__in=roles)
                credentials = getattr(request, "credentials", None)
                if not credentials:
                    return OCPINotOwnerResponse()
                request.credentialsrole = request.credentials.roles.filter(
                    criteria
                ).first()
                if (
                    not request.credentials.is_hub
                    and not matching_operator(request, country_code, party_id)
                    and not request.user.is_superuser
                ):
                    return OCPINotOwnerResponse()
            if not hasattr(request, "credentialsrole") or not request.credentialsrole:
                return OCPIBadRequestResponse(
                    f"To do this, you need to have credentials with one of these roles: {roles}."
                )
            kwargs.update(
                {"data": data, "country_code": country_code, "party_id": party_id}
            )
            return func(self, request, *args, **kwargs)

        # Explicitly setting the __name__ attribute to match the original function's name
        wrapper.__name__ = func.__name__
        requires_sender_role.__name__ = func.__name__
        return wrapper

    # decorator.__name__ = func.__name__
    return decorator


def requires_credentialsrole(func):
    """
    Used for any method that receives a country_code and a party_id.
    This decorator finds the corresponding credentialsrole
    and changes the country_code and party_id arguments to
    a credentialsrole object before calling the decorated function.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        country_code = kwargs.get("country_code")
        party_id = kwargs.get("party_id")
        if not all([country_code, party_id]):
            return OCPIBadRequestResponse(
                "This endpoint requires country_code and party_id"
            )
        credentialsrole = CredentialsRole.get_if_exists(
            country_code__iexact=country_code,
            party_id__iexact=party_id,
            multiple_is_ok_just_get_the_first_one=True,
        )
        return func(*args, credentialsrole=credentialsrole, **kwargs)

    return wrapper


def requires_last_updated(func):
    """For most PATCH requests, the last_updated field is required by the OCPI specification"""

    def wrapper(self, request, *args, **kwargs):
        data = request.data
        if "last_updated" not in data:
            return OCPIBadRequestResponse(
                "The field last_updated is required in the request body when doing PATCH."
            )
        return func(self, request, *args, **kwargs)

    return wrapper
