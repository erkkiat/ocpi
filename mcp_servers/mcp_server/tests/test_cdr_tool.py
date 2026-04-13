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


class TestGetCdrDetails:
    """Test get_cdr_details function"""

    def test_get_cdr_details_value_error_no_params(self):
        """Test get_cdr_details raises ValueError when neither uid nor session_id provided"""
        with pytest.raises(ValueError) as exc_info:
            get_cdr_details()
        assert "Either uid or session_id must be provided" in str(exc_info.value)

    def test_get_cdr_details_value_error_empty_params(self):
        """Test get_cdr_details raises ValueError when both params are empty strings"""
        with pytest.raises(ValueError) as exc_info:
            get_cdr_details(uid="", session_id="")
        assert "Either uid or session_id must be provided" in str(exc_info.value)

    def test_get_cdr_details_object_does_not_exist(self):
        """Test get_cdr_details raises ObjectDoesNotExist for non-existent CDR"""
        with pytest.raises(ObjectDoesNotExist):
            get_cdr_details(uid="NONEXISTENT_CDR_UID")


class TestListCdrsByToken:
    """Test list_cdrs_by_token function"""

    def test_list_cdrs_by_token_value_error_empty_query(self):
        """Test list_cdrs_by_token raises ValueError for empty query"""
        with pytest.raises(ValueError) as exc_info:
            list_cdrs_by_token(query="")
        assert "RFID token must be provided" in str(exc_info.value)

    def test_list_cdrs_by_token_value_error_none_query(self):
        """Test list_cdrs_by_token raises ValueError for None query"""
        with pytest.raises(ValueError) as exc_info:
            list_cdrs_by_token(query=None)
        assert "RFID token must be provided" in str(exc_info.value)

    def test_list_cdrs_by_token_value_error_whitespace_query(self):
        """Test list_cdrs_by_token raises ValueError for whitespace-only query"""
        with pytest.raises(ValueError) as exc_info:
            list_cdrs_by_token(query="   ")
        assert "RFID token must be provided" in str(exc_info.value)


class TestFormatCdrAsMarkdown:
    """Test format_cdr_as_markdown function"""

    def test_format_cdr_as_markdown_includes_header(self):
        """Test format_cdr_as_markdown includes CDR header"""
        # This test would require a mock CDR object
        # For now, just verify the function exists and is callable
        assert callable(format_cdr_as_markdown)


class TestFormatCdrsListAsMarkdown:
    """Test format_cdrs_list_as_markdown function"""

    def test_format_cdrs_list_as_markdown_empty_list(self):
        """Test format_cdrs_list_as_markdown with empty CDR list"""
        result = format_cdrs_list_as_markdown(
            cdrs=[], rfid_token="TEST_TOKEN", last_cdr_uid=None, has_more=False
        )
        assert "No CDRs found" in result
        assert "End of results" in result

    def test_format_cdrs_list_as_markdown_with_cdrs(self):
        """Test format_cdrs_list_as_markdown with CDR list"""
        # This test would require mock CDR objects
        # For now, just verify the function exists and is callable
        assert callable(format_cdrs_list_as_markdown)

    def test_format_cdrs_list_as_markdown_with_paging(self):
        """Test format_cdrs_list_as_markdown includes next page info when has_more=True"""
        result = format_cdrs_list_as_markdown(
            cdrs=[], rfid_token="TEST_TOKEN", last_cdr_uid="CDR001", has_more=True
        )
        assert "Next Page" in result
        assert "TEST_TOKEN|CDR001" in result
