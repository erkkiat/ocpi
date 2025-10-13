from unittest.mock import patch

import pytest
from django.conf import settings
import responses
from django.urls import reverse

from ocpi22.choices import OcpiRolesEnum
from ocpi22.models.location import Connector, Location
from ocpi22.ocpi.auth import get_credentialsrole
from ocpi22.tests.factories import LocationFactory, EvseFactory, ConnectorFactory
from ocpiconnector.ocpi_identities import get_our_party
from webhooks.choices import WebhookType, RemoteCommandType
from webhooks.factories import WebhookFactory


@pytest.fixture
def connector_without_tariff():
    Location.objects.all().delete()
    location = LocationFactory(uid="location-without-tariff")
    evse = EvseFactory(location=location)

    connector = ConnectorFactory(uid="connector_without_tariff")
    evse.connectors.set([connector])
    location.evses.set([evse])

    Connector.objects.filter(uid="connector_without_tariff").first().tariff_ids.set([])

    return connector


class TestHubjectApi:
    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "api_client, expected_status_code",
        [
            pytest.param("client", 401, id="Unauthenticated user getting unauthorized"),
            pytest.param(
                "authenticated_user_client",
                200,
                id="Authenticated user can access evse full load api",
            ),
            pytest.param(
                "admin_user_client", 200, id="Admin user can access evse full load api"
            ),
            pytest.param(
                "super_user_client", 200, id="Super user can access evse full load api"
            ),
        ],
    )
    def test_evse_full_load_api_can_be_accessed_with_proper_credentials(
        self, api_client, expected_status_code, request
    ):
        url = reverse("hubject-api:hubject-evse-full-load")
        client = request.getfixturevalue(api_client)

        response = client.post(url)
        assert response.status_code == expected_status_code

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "api_client, expected_status_code",
        [
            pytest.param("client", 401, id="Unauthenticated user getting unauthorized"),
            pytest.param(
                "authenticated_user_client",
                200,
                id="Authenticated user can access pricing products full load api",
            ),
            pytest.param(
                "admin_user_client",
                200,
                id="Admin user can access pricing products full load api",
            ),
            pytest.param(
                "super_user_client",
                200,
                id="Super user can access pricing products full load api",
            ),
        ],
    )
    def test_pricing_products_full_load_api_can_be_accessed_with_proper_credentials(
        self, api_client, expected_status_code, request
    ):
        url = reverse("hubject-api:hubject-pricing-full-load")
        client = request.getfixturevalue(api_client)

        response = client.post(url)
        assert response.status_code == expected_status_code

    @pytest.mark.django_db
    @responses.activate
    def test_evse_full_load_api_returns_200_OK(
        self, authenticated_user_client, hubject_successful_response, helsinki_location
    ):
        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/FI*CPO/data-records",
            json=hubject_successful_response,
            status=200,
        )

        url = "/api/hubject/2.3/evses/full-load/"
        response = authenticated_user_client.post(url)
        assert response.status_code == 200
        assert response.json() == hubject_successful_response

    @pytest.mark.django_db
    def test_evse_full_load_api_returns_no_evse_records_found(
        self, authenticated_user_client
    ):
        url = "/api/hubject/2.3/evses/full-load/"
        response = authenticated_user_client.post(url)
        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": "No EvseDataRecords found for operator FI*CPO",
        }

    @pytest.mark.django_db
    def test_evse_full_load_api_returns_no_tariffs_found_for_evses(
        self, authenticated_user_client, connector_without_tariff
    ):
        url = "/api/hubject/2.3/evses/full-load/"
        response = authenticated_user_client.post(url)
        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": "No tariff were found for one or more of the evses.",
        }

    @responses.activate
    @pytest.mark.django_db
    def test_start_pricing_products_full_load_returns_200_OK(
        self, authenticated_user_client, hubject_successful_response, smp1_solid_tariff
    ):
        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}dynamicpricing/v10/operators/FI*CPO/pricing-products",
            json=hubject_successful_response,
            status=200,
        )

        url = "/api/hubject/2.3/pricing-products/full-load/"
        response = authenticated_user_client.post(url)
        assert response.status_code == 200
        assert response.json() == hubject_successful_response

    @pytest.mark.django_db
    def test_start_pricing_products_full_load_returns_no_solid_tariffs_found(
        self, authenticated_user_client, hubject_successful_response
    ):
        party = get_our_party(OcpiRolesEnum.CPO)

        url = "/api/hubject/2.3/pricing-products/full-load/"
        response = authenticated_user_client.post(url)
        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": f"No Solid Tariffs found for {str(party)}",
        }


@pytest.mark.django_db
def test_send_charge_detail_record_returns_401_for_unauthenticated_user(
    client, ocpi_cdr
):
    url = f"/api/hubject/2.3/cdr/?session_id={ocpi_cdr.session_id}/"
    with patch(
        "integrations.hubject.services.HubjectService.post_eroaming_charge_detail_record"
    ) as mock_post:
        mock_post.return_value = {
            "success": True,
            "message": "Response from hubject APIs",
        }
        response = client.post(url)
        assert response.status_code == 401


@pytest.mark.django_db
def test_send_charge_detail_record_success(authenticated_user_client, ocpi_cdr):
    url = f"/api/hubject/2.3/cdr/?session_id={ocpi_cdr.session_id}/"
    with patch(
        "integrations.hubject.services.HubjectService.post_eroaming_charge_detail_record"
    ) as mock_post:
        mock_post.return_value = {
            "success": True,
            "message": "Response from hubject APIs",
        }
        response = authenticated_user_client.post(url)
        assert response.status_code == 200


@pytest.mark.django_db
def test_send_charge_detail_record_missing_session_id(
    authenticated_user_client, ocpi_cdr
):
    url = "/api/hubject/2.3/cdr/"

    response = authenticated_user_client.post(url)

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {"type": "missing", "loc": ["query", "session_id"], "msg": "Field required"}
        ]
    }


@pytest.mark.django_db
def test_send_charge_detail_record_hubject_error(authenticated_user_client, ocpi_cdr):
    url = f"/api/hubject/2.3/cdr/?session_id={ocpi_cdr.session_id}/"
    with patch(
        "integrations.hubject.services.HubjectService.post_eroaming_charge_detail_record"
    ) as mock_post:
        mock_post.return_value = {
            "success": False,
            "errorType": "Hubject server Error",
            "error": "Hubject server returned 500. Retrying...",
        }
        response = authenticated_user_client.post(url)

        assert response.status_code == 503
        assert response.json() == {
            "success": False,
            "errorType": "Hubject server Error",
            "error": "Hubject server returned 500. Retrying...",
        }


@pytest.mark.django_db
@responses.activate
def test_receive_remote_start_command_with_valid_data_returns_200(
    authenticated_user_client, remote_command_payload
):
    WebhookFactory(
        type=WebhookType.REMOTE_COMMAND,
        command_type=RemoteCommandType.START_SESSION,
        url="http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
    )
    responses.add(
        responses.POST,
        "http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
        json={"data": {"result": "ACCEPTED"}},
        status=200,
    )
    with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
        mock_auth.return_value = True
        url = reverse("hubject-api:hubject-remote-start", args=["DE-DCB"])
        response = authenticated_user_client.post(
            url, data=remote_command_payload, format="json"
        )
        assert response.status_code == 200
        assert response.json() == {
            "cpo_partner_session_id": response.json().get(
                "cpo_partner_session_id"
            ),  # ignored in assert
            "emp_partner_session_id": "2345ABC",
            "session_id": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
            "status_code": {
                "Code": "000",
                "Description": None,
                "AdditionalInfo": None,
            },
            "result": True,
        }


@pytest.mark.django_db
@responses.activate
def test_remote_start_returns_200_for_minimal_data(
    authenticated_user_client, remote_command_payload
):
    get_credentialsrole.cache_clear()
    WebhookFactory(
        type=WebhookType.REMOTE_COMMAND,
        command_type=RemoteCommandType.START_SESSION,
        url="http://testserver.test/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
    )
    responses.add(
        responses.POST,
        "http://testserver.test/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
        json={"data": {"result": "ACCEPTED"}},
        status=200,
    )
    with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
        mock_auth.return_value = True
        url = reverse("hubject-api:hubject-remote-start", args=["DE-DCB"])
        remote_command_payload.pop("CPOPartnerSessionID")
        remote_command_payload.pop("EMPPartnerSessionID")
        remote_command_payload.pop("PartnerProductID")
        response = authenticated_user_client.post(
            url, data=remote_command_payload, format="json"
        )
        assert response.status_code == 200
        assert response.json() == {
            "cpo_partner_session_id": response.json().get(
                "cpo_partner_session_id"
            ),  # ignored in assert
            "emp_partner_session_id": None,
            "session_id": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
            "status_code": {
                "Code": "000",
                "Description": None,
                "AdditionalInfo": None,
            },
            "result": True,
        }


def test_remote_start_returns_400_for_invalid_data(
    authenticated_user_client, remote_command_payload
):
    with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
        mock_auth.return_value = True
        url = reverse("hubject-api:hubject-remote-start", args=["DE-DCB"])
        remote_command_payload["SessionID"] = "invalid"
        response = authenticated_user_client.post(
            url, data=remote_command_payload, format="json"
        )
        assert response.status_code == 400
        assert response.json() == {
            "cpo_partner_session_id": response.json().get("cpo_partner_session_id"),
            "emp_partner_session_id": "2345ABC",
            "session_id": None,
            "status_code": {
                "Code": "022",
                "Description": None,
                "AdditionalInfo": None,
            },
            "result": False,
        }


def test_remote_start_returns_503_for_failure_in_executing_command(
    authenticated_user_client, remote_command_payload
):
    with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
        with patch(
            "integrations.hubject.services.HubjectService.process_remote_start_command"
        ) as mock_service:
            mock_auth.return_value = True
            mock_service.side_effect = Exception("Service failure")
            url = reverse("hubject-api:hubject-remote-start", args=["DE-DCB"])
            response = authenticated_user_client.post(
                url, data=remote_command_payload, format="json"
            )
            assert response.status_code == 503
            assert response.json() == {
                "cpo_partner_session_id": response.json().get("cpo_partner_session_id"),
                "emp_partner_session_id": "2345ABC",
                "session_id": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
                "status_code": {
                    "Code": "021",
                    "Description": None,
                    "AdditionalInfo": None,
                },
                "result": False,
            }


def test_remote_start_returns_400_for_mismatching_provider_id(
    authenticated_user_client, remote_command_payload
):
    with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
        mock_auth.return_value = True
        url = reverse("hubject-api:hubject-remote-start", args=["DE-DDB"])
        response = authenticated_user_client.post(
            url, data=remote_command_payload, format="json"
        )
        assert response.status_code == 400
        assert response.json() == {
            "cpo_partner_session_id": response.json().get("cpo_partner_session_id"),
            "emp_partner_session_id": "2345ABC",
            "session_id": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
            "status_code": {
                "Code": "022",
                "Description": None,
                "AdditionalInfo": None,
            },
            "result": False,
        }


class TestHubjectRemoteStopAPI:
    @pytest.mark.django_db
    @responses.activate
    def test_receive_remote_stop_command_with_valid_data_returns_200(
        self,
        authenticated_user_client,
        remote_stop_command_payload,
        remote_stop_session,
    ):
        WebhookFactory(
            type=WebhookType.REMOTE_COMMAND,
            command_type=RemoteCommandType.STOP_SESSION,
            url="http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
        )
        responses.add(
            responses.POST,
            "http://localhost/api/cpo/v2/chargepoint/remote_command_result/MSPSession/",
            json={"data": {"result": "ACCEPTED"}},
            status=200,
        )
        with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
            mock_auth.return_value = True
            url = reverse("hubject-api:hubject-remote-stop", args=["DE-DCB"])
            response = authenticated_user_client.post(
                url, data=remote_stop_command_payload, format="json"
            )
            assert response.status_code == 200
            assert response.json() == {
                "cpo_partner_session_id": response.json().get(
                    "cpo_partner_session_id"
                ),  # ignored in assert
                "emp_partner_session_id": "2345ABC",
                "session_id": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
                "status_code": {
                    "Code": "000",
                    "Description": None,
                    "AdditionalInfo": None,
                },
                "result": True,
            }

    def test_remote_stop_returns_400_for_invalid_data(
        self, authenticated_user_client, remote_stop_command_payload
    ):
        with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
            mock_auth.return_value = True
            url = reverse("hubject-api:hubject-remote-stop", args=["DE-DCB"])
            remote_stop_command_payload["SessionID"] = "invalid"
            response = authenticated_user_client.post(
                url, data=remote_stop_command_payload, format="json"
            )
            assert response.status_code == 400
            assert response.json() == {
                "cpo_partner_session_id": response.json().get("cpo_partner_session_id"),
                "emp_partner_session_id": "2345ABC",
                "session_id": None,
                "status_code": {
                    "Code": "022",
                    "Description": None,
                    "AdditionalInfo": None,
                },
                "result": False,
            }

    def test_remote_stop_returns_503_for_failure_in_executing_command(
        self, authenticated_user_client, remote_stop_command_payload
    ):
        with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
            with patch(
                "integrations.hubject.services.HubjectService.process_remote_stop_command"
            ) as mock_service:
                mock_auth.return_value = True
                mock_service.side_effect = Exception("Service failure")
                url = reverse("hubject-api:hubject-remote-stop", args=["DE-DCB"])
                response = authenticated_user_client.post(
                    url, data=remote_stop_command_payload, format="json"
                )
                assert response.status_code == 503
                assert response.json() == {
                    "cpo_partner_session_id": response.json().get(
                        "cpo_partner_session_id"
                    ),
                    "emp_partner_session_id": "2345ABC",
                    "session_id": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
                    "status_code": {
                        "Code": "021",
                        "Description": None,
                        "AdditionalInfo": None,
                    },
                    "result": False,
                }

    def test_remote_stop_returns_400_for_mismatching_provider_id(
        self, authenticated_user_client, remote_stop_command_payload
    ):
        with patch("ocpi22.ocpi.auth.HubjectCertAuth.authenticate") as mock_auth:
            mock_auth.return_value = True
            url = reverse("hubject-api:hubject-remote-stop", args=["DE-DDB"])
            response = authenticated_user_client.post(
                url, data=remote_stop_command_payload, format="json"
            )
            assert response.status_code == 400
            assert response.json() == {
                "cpo_partner_session_id": response.json().get("cpo_partner_session_id"),
                "emp_partner_session_id": "2345ABC",
                "session_id": "f98efba4-02d8-4fa0-b810-9a9d50d25527",
                "status_code": {
                    "Code": "022",
                    "Description": None,
                    "AdditionalInfo": None,
                },
                "result": False,
            }
