
import pytest
import base64

from django.urls import reverse
from ocpi22.tests.factories import OCPISessionFactory, CdrFactory, CredentialsRoleFactory, CdrTokenFactory
from ocpi22.models.session import Session
from ocpi22.models.cdr import Cdr


@pytest.fixture
def billed_to_fi_msp():
    return CredentialsRoleFactory(country_code="FI", party_id="MSP", role="EMSP")

@pytest.fixture
def billed_to_fi_sdr():
    return CredentialsRoleFactory(country_code="FI", party_id="SDR", role="EMSP")

@pytest.fixture
def ocpi_master_fi_cpo():
    return CredentialsRoleFactory(country_code="FI", party_id="CPO", role="CPO")

@pytest.fixture
def cdr_fi_msp(ocpi_master_fi_cpo, billed_to_fi_msp):
    token = CdrTokenFactory(ocpi_master=billed_to_fi_msp, uid="TOKEN1", contract_id="C1")
    return CdrFactory(ocpi_master=ocpi_master_fi_cpo, uid="CDR1", billed_to=billed_to_fi_msp, cdr_token=token, session_id="SID1")

@pytest.fixture
def cdr_fi_sdr(ocpi_master_fi_cpo, billed_to_fi_sdr):
    token2 = CdrTokenFactory(ocpi_master=billed_to_fi_sdr, uid="TOKEN2", contract_id="C2")
    return CdrFactory(ocpi_master=ocpi_master_fi_cpo, uid="CDR2", billed_to=billed_to_fi_sdr, cdr_token=token2, session_id="SID2")

@pytest.fixture
def session_fi_msp(ocpi_master_fi_cpo, billed_to_fi_msp):
    return OCPISessionFactory(uid="OCPISESSION1", ocpi_master=ocpi_master_fi_cpo, billed_to=billed_to_fi_msp)

@pytest.fixture
def session_fi_sdr(ocpi_master_fi_cpo, billed_to_fi_sdr):
    return OCPISessionFactory(uid="OCPISESSION2", ocpi_master=ocpi_master_fi_cpo, billed_to=billed_to_fi_sdr)

@pytest.mark.django_db
def test_superuser_can_get_all_sessions(super_user_client, session_fi_msp, session_fi_sdr):
    url = reverse("session-list", kwargs={"version": "2.2.1"})
    
    response = super_user_client.get(url)
    
    assert response.status_code == 200
    assert len(response.data['data']) == 2

@pytest.mark.django_db
def test_superuser_can_get_all_cdrs(super_user_client, cdr_fi_msp, cdr_fi_sdr):
    url = reverse("cdr-list", kwargs={"version": "2.2.1"})
    
    response = super_user_client.get(url)
    
    assert response.status_code == 200
    assert len(response.data['data']) == 2

@pytest.mark.django_db
def test_each_partner_can_only_get_their_own_sessions(client, session_fi_msp, session_fi_sdr):
    msp = session_fi_msp.billed_to
    token = msp.credentials.ours
    token_b64 = base64.b64encode(token.encode()).decode()
    
    headers = {
        'HTTP_AUTHORIZATION': f'Token {token_b64}',
        'HTTP_OCPI_FROM_COUNTRY_CODE': msp.country_code,
        'HTTP_OCPI_FROM_PARTY_ID': msp.party_id,
        'HTTP_OCPI_TO_COUNTRY_CODE': session_fi_sdr.ocpi_master.country_code,
        'HTTP_OCPI_TO_PARTY_ID': session_fi_sdr.ocpi_master.party_id,
    }
    client.credentials(**headers)
    
    url = reverse("session-list", kwargs={"version": "2.2.1"})
    response = client.get(url)
    
    assert response.status_code == 200
    assert len(response.data['data']) == 1
    assert response.data['data'][0]['id'] == session_fi_msp.uid


@pytest.mark.django_db
def test_each_partner_can_only_get_their_own_cdrs(client, cdr_fi_msp, cdr_fi_sdr):
    msp = cdr_fi_msp.billed_to
    token = msp.credentials.ours
    token_b64 = base64.b64encode(token.encode()).decode()

    headers = {
        'HTTP_AUTHORIZATION': f'Token {token_b64}',
        'HTTP_OCPI_FROM_COUNTRY_CODE': msp.country_code,
        'HTTP_OCPI_FROM_PARTY_ID': msp.party_id,
        'HTTP_OCPI_TO_COUNTRY_CODE': cdr_fi_msp.ocpi_master.country_code,
        'HTTP_OCPI_TO_PARTY_ID': cdr_fi_msp.ocpi_master.party_id,
    }
    client.credentials(**headers)

    url = reverse("cdr-list", kwargs={"version": "2.2.1"})
    response = client.get(url)

    assert response.status_code == 200
    assert len(response.data['data']) == 1
    assert response.data['data'][0]['id'] == cdr_fi_msp.uid

@pytest.mark.django_db
def test_authorized_user_get_session_list_returns_status_code_unauthorized_401(client):
    OCPISessionFactory()
    url = reverse("session-list", kwargs={"version": "2.2.1"})
    response = client.get(url)
    assert response.status_code == 401

@pytest.mark.django_db
def test_superuser_get_empty_list_when_no_sessions_in_database(super_user_client):
    Session.objects.all().delete()
    
    url = reverse("session-list", kwargs={"version": "2.2.1"})
    response = super_user_client.get(url)
    
    assert response.status_code == 200
    assert len(response.data['data']) == 0

@pytest.mark.django_db
def test_superuser_get_empty_list_when_no_cdrs_in_database(super_user_client):
    Cdr.objects.all().delete()
    
    url = reverse("cdr-list", kwargs={"version": "2.2.1"})
    response = super_user_client.get(url)
    
    assert response.status_code == 200
    assert len(response.data['data']) == 0
