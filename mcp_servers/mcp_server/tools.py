"""
MCP Server Tools Implementation

This module contains tool functions following the MCP tool implementation principles:
- Pure functions that accept parameters and return markdown-formatted strings
- Use Django ORM with select_related() for foreign keys and prefetch_related() for many-to-many
- Raise ValueError for invalid input, let Django raise ObjectDoesNotExist for missing data
- Separate data retrieval from formatting logic
- All tools return markdown-formatted strings for AI readability
"""

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from ocpi22.models.cdr import Cdr
from ocpi22.models.session import Session


def get_cdr_details(uid=None, session_id=None):
    """
    Retrieve CDR details by uid or session_id with related tariffs and session.

    Args:
        uid: CDR uid (optional)
        session_id: Session ID (optional)

    Returns:
        str: Markdown formatted CDR details

    Raises:
        ValueError: If neither uid nor session_id is provided
        ObjectDoesNotExist: If CDR not found
    """
    if not uid and not session_id:
        raise ValueError("Either uid or session_id must be provided")

    # Query CDR with efficient related object loading
    queryset = Cdr.objects.select_related(
        "ocpi_master",
        "cdr_token",
        "cdr_location",
    ).prefetch_related("tariffs__tariff_elements__price_components")

    if uid:
        cdr = queryset.get(uid=uid)
    else:
        cdr = queryset.get(session_id=session_id)

    # Get session details if available
    session = None
    try:
        session = (
            Session.objects.select_related(
                "location",
                "evse",
                "connector",
                "cdr_token",
            ).get(uid=cdr.session_id)
            if cdr.session_id
            else None
        )
    except ObjectDoesNotExist:
        # Session may not exist for this CDR; proceed with CDR-only output.
        session = None

    return format_cdr_as_markdown(cdr, session)


def format_cdr_as_markdown(cdr, session=None):
    """
    Format CDR and related data as human/AI-readable markdown.

    Args:
        cdr: Cdr object
        session: Session object (optional)

    Returns:
        str: Markdown formatted content
    """
    lines = []

    # Header
    lines.append("# Charge Detail Record (CDR)")
    lines.append(f"**UID:** `{cdr.uid}`")
    lines.append(f"**Session ID:** `{cdr.session_id or 'N/A'}`")
    lines.append("")

    # Timing
    lines.append("## Timing")
    lines.append(f"- **Start:** {cdr.start_date_time}")
    lines.append(f"- **End:** {cdr.end_date_time}")
    lines.append(f"- **Total Duration:** {cdr.total_time:.2f} hours")
    if cdr.reservation_start_date_time:
        lines.append(f"- **Reservation Start:** {cdr.reservation_start_date_time}")
    lines.append("")

    # Token Information
    lines.append("## Token Information")
    lines.append(f"- **Token UID:** `{cdr.cdr_token_uid}`")
    lines.append(f"- **Token Type:** {cdr.cdr_token_type}")
    lines.append(f"- **Contract ID:** `{cdr.cdr_token_contract_id}`")
    lines.append(f"- **Auth Method:** {cdr.auth_method}")
    if cdr.authorization_reference:
        lines.append(f"- **Auth Reference:** `{cdr.authorization_reference}`")
    lines.append("")

    # Location Information
    lines.append("## Location Information")
    lines.append(f"- **Location UID:** `{cdr.cdr_location_uid}`")
    lines.append(f"- **Location Name:** {cdr.cdr_location_name or 'N/A'}")
    lines.append(f"- **Address:** {cdr.cdr_location_address}")
    lines.append(f"- **City:** {cdr.cdr_location_city}")
    lines.append(f"- **Postal Code:** {cdr.cdr_location_postal_code or 'N/A'}")
    lines.append(f"- **State:** {cdr.cdr_location_state or 'N/A'}")
    lines.append(f"- **Country:** {cdr.cdr_location_country}")
    lines.append(
        f"- **Coordinates:** ({cdr.cdr_location_latitude}, {cdr.cdr_location_longitude})"
    )
    lines.append("")

    # EVSE Information
    lines.append("## EVSE Information")
    lines.append(f"- **EVSE UID:** `{cdr.cdr_location_evse_uid}`")
    lines.append(f"- **EVSE ID:** `{cdr.cdr_location_evse_id}`")
    lines.append(f"- **Connector ID:** `{cdr.cdr_location_connector_id}`")
    lines.append(f"- **Connector Standard:** {cdr.cdr_location_connector_standard}")
    lines.append(f"- **Connector Format:** {cdr.cdr_location_connector_format}")
    lines.append(f"- **Connector Power Type:** {cdr.cdr_location_connector_power_type}")
    lines.append("")

    # Session Details (if available)
    if session:
        lines.append("## Session Details")
        lines.append(f"- **Status:** {session.status}")
        lines.append(f"- **Energy Charged:** {session.kwh:.3f} kWh")
        lines.append(f"- **Meter ID:** {session.meter_id or 'N/A'}")
        if session.total_cost_excl_vat is not None:
            lines.append(
                f"- **Total Cost (excl. VAT):** {session.total_cost_excl_vat:.2f} {session.currency}"
            )
        if session.total_cost_incl_vat is not None:
            lines.append(
                f"- **Total Cost (incl. VAT):** {session.total_cost_incl_vat:.2f} {session.currency}"
            )
        lines.append("")

    # Cost Information
    lines.append("## Cost Information")
    lines.append(f"- **Currency:** {cdr.currency}")
    if cdr.total_cost_excl_vat is not None:
        lines.append(f"- **Total Cost (excl. VAT):** {cdr.total_cost_excl_vat:.2f}")
    if cdr.total_cost_incl_vat is not None:
        lines.append(f"- **Total Cost (incl. VAT):** {cdr.total_cost_incl_vat:.2f}")
    lines.append(f"- **Total Energy:** {cdr.total_energy:.3f} kWh")
    lines.append(f"- **Credit:** {'Yes' if cdr.credit else 'No'}")
    if cdr.credit_reference:
        lines.append(f"- **Credit Reference:** `{cdr.credit_reference.uid}`")
    lines.append("")

    # Tariffs
    lines.append("## Tariffs")
    if cdr.tariffs.exists():
        for tariff in cdr.tariffs.all():
            lines.append(f"### Tariff: `{tariff.uid}`")
            lines.append(f"- **Currency:** {tariff.currency}")
            lines.append(f"- **Type:** {tariff.type or 'Regular'}")
            if tariff.min_price_incl_vat or tariff.min_price_excl_vat:
                lines.append(
                    f"- **Min Price:** {tariff.min_price_incl_vat or tariff.min_price_excl_vat}"
                )
            if tariff.max_price_incl_vat or tariff.max_price_excl_vat:
                lines.append(
                    f"- **Max Price:** {tariff.max_price_incl_vat or tariff.max_price_excl_vat}"
                )
            lines.append(f"- **Last Updated:** {tariff.last_updated or 'N/A'}")

            # Tariff Elements
            for element in tariff.tariff_elements.all():
                lines.append("  **Tariff Element:**")
                if element.start_time:
                    lines.append(
                        f"  - Time Range: {element.start_time} - {element.end_time or '24:00'}"
                    )
                if element.day_of_week:
                    lines.append(f"  - Days: {', '.join(element.day_of_week)}")
                if element.min_kwh or element.max_kwh:
                    lines.append(
                        f"  - Energy Range: {element.min_kwh or 0} - {element.max_kwh or '∞'} kWh"
                    )

                # Price Components
                for pc in element.price_components.all():
                    lines.append(f"  - **Price Component:** {pc.type}")
                    lines.append(f"    - Price: {pc.price} {tariff.currency}")
                    lines.append(f"    - VAT: {pc.vat or 0}%")
                    lines.append(f"    - Step Size: {pc.step_size}")
            lines.append("")
    else:
        lines.append("No tariffs associated with this CDR.")
        lines.append("")

    # OCPI Information
    lines.append("## OCPI Information")
    lines.append(f"- **OCPI Master:** {cdr.ocpi_master}")
    lines.append(f"- **Billed To:** {cdr.billed_to or 'N/A'}")
    lines.append(f"- **Last Updated:** {cdr.last_updated or 'N/A'}")
    lines.append(f"- **Created:** {cdr.created}")
    lines.append("")

    # Charging Periods
    if cdr.charging_periods:
        lines.append("## Charging Periods")
        lines.append("```json")
        import json

        lines.append(json.dumps(cdr.charging_periods, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def list_cdrs_by_token(query: str) -> str:
    """
    List CDRs by RFID token with cursor-based paging.

    Args:
        query: Pipe-separated parameters: "rfid_token|last_cdr_uid"
               - rfid_token: Required RFID token UID to filter by
               - last_cdr_uid: Optional cursor - UID of last CDR from previous page
               Example: "TOKEN001" for first page, "TOKEN001|CDR-005" for next page

    Returns:
        str: Markdown formatted list of CDRs with next page query if available

    Raises:
        ValueError: If rfid_token is not provided
    """
    # Parse query parameter
    if query is None:
        raise ValueError("RFID token must be provided in query parameter")
    parts = query.split("|")
    rfid_token = parts[0].strip() if parts else ""
    last_cdr_uid = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

    if not rfid_token:
        raise ValueError("RFID token must be provided in query parameter")

    # Build queryset with cursor-based paging
    queryset = (
        Cdr.objects.select_related(
            "ocpi_master",
            "cdr_token",
            "cdr_location",
        )
        .prefetch_related("tariffs__tariff_elements__price_components")
        .filter(cdr_token_uid=rfid_token)
        .order_by("start_date_time", "uid")
    )

    # Apply cursor filter if last_cdr_uid is provided
    if last_cdr_uid:
        try:
            last_cdr = Cdr.objects.get(uid=last_cdr_uid)
            # Filter for CDRs after the cursor (by start_date_time and UID for stability)
            queryset = queryset.filter(
                start_date_time__gt=last_cdr.start_date_time
            ) | queryset.filter(
                start_date_time=last_cdr.start_date_time, uid__gt=last_cdr.uid
            )
            queryset = queryset.order_by("start_date_time", "uid")
        except Cdr.DoesNotExist:
            # If cursor doesn't exist, start from beginning
            pass

    # Limit to configured page size
    page_size = settings.MCP_SERVER_PAGE_SIZE
    cdrs = queryset[
        : page_size + 1
    ]  # Fetch page_size + 1 to determine if there's a next page
    cdrs_list = list(cdrs)
    has_more = len(cdrs_list) > page_size
    cdrs_list = cdrs_list[:page_size]

    # Format results
    return format_cdrs_list_as_markdown(
        cdrs_list,
        rfid_token=rfid_token,
        last_cdr_uid=cdrs_list[-1].uid if cdrs_list else None,
        has_more=has_more,
    )


def format_cdrs_list_as_markdown(cdrs, rfid_token, last_cdr_uid=None, has_more=False):
    """
    Format a list of CDRs as human/AI-readable markdown with paging info.

    Args:
        cdrs: List of Cdr objects
        rfid_token: The RFID token used for filtering
        last_cdr_uid: UID of the last CDR in this page (for next page cursor)
        has_more: Whether there are more results available

    Returns:
        str: Markdown formatted content
    """
    lines = []

    # Header
    lines.append(f"# Charge Detail Records (CDRs) for RFID Token: `{rfid_token}`")
    lines.append(f"**Showing:** {len(cdrs)} result(s)")
    lines.append("")

    if not cdrs:
        lines.append("No CDRs found for this RFID token.")
        lines.append("")
        lines.append("---")
        if has_more and last_cdr_uid:
            next_query = f"{rfid_token}|{last_cdr_uid}"
            lines.append("## Next Page")
            lines.append("To get the next page, use:")
            lines.append("``")
            lines.append(f"list_cdrs_by_token(query='{next_query}')")
            lines.append("``")
            lines.append("")
        else:
            lines.append("**End of results**")
            lines.append("")
        return "\n".join(lines)

    # List each CDR
    for idx, cdr in enumerate(cdrs, 1):
        lines.append(f"## CDR {idx}")
        lines.append(f"- **UID:** `{cdr.uid}`")
        lines.append(f"- **Session ID:** `{cdr.session_id or 'N/A'}`")
        lines.append(f"- **Start:** {cdr.start_date_time}")
        lines.append(f"- **End:** {cdr.end_date_time}")
        lines.append(f"- **Total Duration:** {cdr.total_time:.2f} hours")
        lines.append(f"- **Token UID:** `{cdr.cdr_token_uid}`")
        lines.append(
            f"- **Location:** {cdr.cdr_location_city}, {cdr.cdr_location_country}"
        )
        lines.append(f"- **Total Energy:** {cdr.total_energy:.3f} kWh")
        if cdr.total_cost_excl_vat is not None:
            lines.append(
                f"- **Total Cost:** {cdr.total_cost_excl_vat:.2f} {cdr.currency}"
            )
        lines.append("")

    # Paging footer
    lines.append("---")
    if has_more and last_cdr_uid:
        next_query = f"{rfid_token}|{last_cdr_uid}"
        lines.append("## Next Page")
        lines.append("To get the next page, use:")
        lines.append("``")
        lines.append(f"list_cdrs_by_token(query='{next_query}')")
        lines.append("``")
        lines.append("")
    else:
        lines.append("**End of results**")
        lines.append("")

    return "\n".join(lines)
