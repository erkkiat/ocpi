from unittest.mock import patch

import pytest

from ocpi22.models.cdr import Cdr


@pytest.mark.django_db
def test_cdr_send_update_url_to_be_without_path_components(
    msp_credentials_with_endpoints, completed_session, clear_all_cache
):
    cdr = Cdr.objects.get(session_id=completed_session.uid)

    with patch("ocpi22.ocpi.util.OcpiModule.send_background_update") as mock_send:
        cdr.send_updates()

    assert mock_send.called_once()
    assert mock_send.call_args.args[1] == "https://localhost/ocpi/cdrs"
