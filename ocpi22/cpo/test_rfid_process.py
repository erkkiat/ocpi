import pytest
from ocpi22.cpo.api import ChargePointViewSet
from ocpiconnector.testutil import OCPIAPIRequestFactory
from util import reverse

api_factory = OCPIAPIRequestFactory()


@pytest.mark.django_db
def test_rfid_process_with_wrong_session_id():
    viewset = ChargePointViewSet()
    request = api_factory.post(reverse("chargepoint-start-transaction"))
    request.data = {"session_id": "NONTEXISTENT"}
    response = viewset.start_transaction(request)
    assert response.status_code == 404
    assert response.data == {"status": "Session matching query does not exist."}
