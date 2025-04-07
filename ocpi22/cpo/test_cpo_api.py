import pytest

from ocpi22.cpo.api import ChargePointOperatorAPIView
from ocpiconnector.party import Party
from ocpiconnector.testutil import OCPIAPIRequestFactory, get_fake_admin
from util import reverse

api_factory = OCPIAPIRequestFactory()


@pytest.mark.django_db
def test_cpo_api_get_main_view_to_check_all_endpoints_exist(default_credentials):
    request = api_factory.get(
        reverse("cpo-api"),
        sender=default_credentials.roles.first(),
        to=Party("FI", "CPO"),
    )
    request.data = {}
    request.user = get_fake_admin()
    request.accepted_media_type = "application/json"
    request.version = "2.2.1"
    response = ChargePointOperatorAPIView().get(request)
    assert response.status_code == 200
