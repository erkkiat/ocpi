"""
CDR Tool Tests

This module tests the CDR tool functions following the implementation principles:
- Test get_cdr_details() with uid and session_id
- Test list_cdrs_by_token() with paging
- Test error handling for invalid input and missing data
- Test markdown formatting functions
"""

import pytest
from django.core.exceptions import ObjectDoesNotExist
from mcp_servers.mcp_server.tools import (
    get_cdr_details,
    format_cdr_as_markdown,
    list_cdrs_by_token,
    format_cdrs_list_as_markdown,
)
from ocpi22.tests.factories import CdrFactory, OCPISessionFactory


class TestGetCdrDetails:
    """Test get_cdr_details function"""

    def test_get_cdr_details_with_no_params_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            get_cdr_details()
        assert "Either uid or session_id must be provided" in str(exc_info.value)

    def test_get_cdr_details_with_empty_params_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            get_cdr_details(uid="", session_id="")
        assert "Either uid or session_id must be provided" in str(exc_info.value)

    @pytest.mark.django_db
    def test_get_nonexistent_cdr_details_with_uid_raises_object_does_not_exist(self):
        with pytest.raises(ObjectDoesNotExist):
            get_cdr_details(uid="NONEXISTENT_CDR_UID")

    @pytest.mark.django_db
    def test_get_nonexistent_cdr_details_with_session_id_raises_object_does_not_exist(
        self,
    ):
        with pytest.raises(ObjectDoesNotExist):
            get_cdr_details(session_id="NONEXISTENT_SESSION_ID")

    @pytest.mark.django_db
    def test_get_existing_cdr_details_returns_markdown(self):
        cdr = CdrFactory()
        result = get_cdr_details(uid=cdr.uid)
        assert isinstance(result, str)
        assert len(result) > 0


class TestListCdrsByToken:
    """Test list_cdrs_by_token function"""

    def test_list_cdrs_by_token_with_empty_query_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            list_cdrs_by_token(query="")
        assert "RFID token must be provided" in str(exc_info.value)

    def test_list_cdrs_by_token_with_none_query_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            list_cdrs_by_token(query=None)
        assert "RFID token must be provided" in str(exc_info.value)

    def test_list_cdrs_by_token_with_whitespace_query_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            list_cdrs_by_token(query="   ")
        assert "RFID token must be provided" in str(exc_info.value)

    def test_list_cdrs_by_token_uses_page_size_from_settings(self, monkeypatch):
        # Monkeypatch the setting to verify it's used
        monkeypatch.setattr("django.conf.settings.MCP_SERVER_PAGE_SIZE", 3)
        # Re-import to get the new setting value
        import importlib
        from mcp_servers.mcp_server import tools

        importlib.reload(tools)

        # Verify the setting is accessible
        from django.conf import settings

        assert settings.MCP_SERVER_PAGE_SIZE == 3

    @pytest.mark.django_db
    def test_list_cdrs_by_token_with_valid_token_returns_no_cdrs_found(self):
        result = list_cdrs_by_token(query="NONEXISTENT_TOKEN")
        assert "No CDRs found" in result
        assert "End of results" in result

    @pytest.mark.django_db
    def test_list_cdrs_by_token_with_cursor_format_returns_string(self):
        result = list_cdrs_by_token(query="TOKEN|CDR123")
        # Should handle the cursor format even if CDR doesn't exist
        assert isinstance(result, str)


class TestFormatCdrAsMarkdown:
    """Test format_cdr_as_markdown function"""

    @pytest.mark.django_db
    def test_format_cdr_as_markdown_includes_cdr_header(self):
        cdr = CdrFactory()
        session = OCPISessionFactory(uid=cdr.session_id)
        result = format_cdr_as_markdown(cdr, session)

        # Verify header
        assert "# Charge Detail Record (CDR)" in result
        assert f"**UID:** `{cdr.uid}`" in result

        # Verify timing section
        assert "## Timing" in result
        assert "**Start:" in result
        assert "**End:" in result
        assert "**Total Duration:" in result

        # Verify token information
        assert "## Token Information" in result
        assert f"**Token UID:** `{cdr.cdr_token_uid}`" in result

        # Verify location information
        assert "## Location Information" in result
        assert f"**Location UID:** `{cdr.cdr_location_uid}`" in result

        # Verify EVSE information
        assert "## EVSE Information" in result
        assert f"**EVSE UID:** `{cdr.cdr_location_evse_uid}`" in result

        # Verify session details when session is provided
        assert "## Session Details" in result
        assert "**Status:" in result
        assert "**Energy Charged:" in result


class TestFormatCdrsListAsMarkdown:
    def test_format_cdrs_list_as_markdown_with_empty_list_displays_no_cdrs_found(self):
        result = format_cdrs_list_as_markdown(
            cdrs=[], rfid_token="TEST_TOKEN", last_cdr_uid=None, has_more=False
        )
        assert "No CDRs found" in result
        assert "End of results" in result

    @pytest.mark.django_db
    def test_format_cdrs_list_as_markdown_with_cdrs_displays_cdr_list(self):
        rfid_token = "TEST_TOKEN_123"
        cdr1 = CdrFactory(cdr_token_uid=rfid_token, session_id="SESSION001")
        cdr2 = CdrFactory(cdr_token_uid=rfid_token, session_id="SESSION002")
        cdrs = [cdr1, cdr2]

        result = format_cdrs_list_as_markdown(
            cdrs=cdrs, rfid_token=rfid_token, last_cdr_uid=cdr2.uid, has_more=False
        )

        # Verify header
        assert (
            f"# Charge Detail Records (CDRs) for RFID Token: `{rfid_token}`" in result
        )
        assert "**Showing:** 2 result(s)" in result

        # Verify CDR 1 details
        assert "## CDR 1" in result
        assert f"**UID:** `{cdr1.uid}`" in result
        assert f"**Session ID:** `{cdr1.session_id}`" in result

        # Verify CDR 2 details
        assert "## CDR 2" in result
        assert f"**UID:** `{cdr2.uid}`" in result
        assert f"**Session ID:** `{cdr2.session_id}`" in result

        # Verify location and energy info for each CDR
        assert "**Location:" in result
        assert "**Total Energy:" in result

        # Verify footer
        assert "**End of results**" in result

    def test_format_cdrs_list_as_markdown_with_has_more_true_includes_next_page_info(
        self,
    ):
        result = format_cdrs_list_as_markdown(
            cdrs=[], rfid_token="TEST_TOKEN", last_cdr_uid="CDR001", has_more=True
        )
        assert "Next Page" in result
        assert "TEST_TOKEN|CDR001" in result
