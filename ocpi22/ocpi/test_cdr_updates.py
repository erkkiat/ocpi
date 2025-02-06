from unittest.mock import patch

import pytest

from ocpi22.ocpi.auth import get_credentialsrole


@pytest.mark.django_db
def test_cdr_send_update_url_to_be_without_path_components(cdr_receiver_credentials, default_ocpi_session_and_cdr):
    get_credentialsrole.cache_clear()
    session, cdr = default_ocpi_session_and_cdr

    with patch("ocpi22.ocpi.util.OcpiModule.send_background_update") as mock_send:
        cdr.send_updates()

    assert mock_send.called_once()
    assert mock_send.call_args.args[1] == "https://example.com/ocpi/cdrs"
