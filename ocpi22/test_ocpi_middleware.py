from unittest.mock import patch

import pytest

from ocpi22.models.credentials import Credentials
from ocpi22.ocpi.headers import make_headers
from ocpi22.tests.factories import CredentialsFactory
from ocpiconnector.party import Party
from util import reverse
from ocpi22.ocpi.headers import uuid as ocpi_uuid


@pytest.mark.django_db
def test_ocpi_221_middleware_sets_x_request_id_and_correlation_id_headers(client):
    token = "ABC123"
    static_uuid = "123"
    CredentialsFactory(ours=token)
    with patch.object(ocpi_uuid, "uuid4", return_value=static_uuid):
        headers = make_headers(
            Credentials.base64(token), to=Party("FI", "CPO"), sender=Party("FI", "MSP")
        )
    response = client.get(
        reverse("token-list"), headers=headers
    )  # Ensure this URL is handled by your view

    assert response.get("X-Request-ID") == static_uuid
    assert response.get("X-Correlation-ID") == static_uuid
