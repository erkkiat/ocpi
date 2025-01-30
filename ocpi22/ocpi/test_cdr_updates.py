from unittest.mock import patch

import pytest

from ocpi22.ocpi.auth import get_credentialsrole


@pytest.mark.django_db
def test_cdr_send_update_url_to_be_without_path_components(
    default_cdr, drop_all_data, cdr_receiver_credentials
):
    get_credentialsrole.cache_clear()

    with patch("ocpi22.ocpi.util.OcpiModule.send_background_update") as mock_send:
        default_cdr.send_updates()

    assert mock_send.called_once()
    assert mock_send.call_args.args[1] == "https://example.com/ocpi/cdrs"
