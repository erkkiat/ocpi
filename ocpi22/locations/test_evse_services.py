import zoneinfo
from datetime import datetime
from unittest.mock import patch

import pytest
import responses
from django.test import override_settings

from ocpi22.locations.services import EvseServices
from ocpi22.models.location import Evse
from ocpi22.tests.factories import EvseFactory, LocationFactory, CredentialsRoleFactory


class TestEvseServices:
    @pytest.fixture
    def evse_patch_payload(self):
        return {
            "status": Evse.AVAILABLE,
            "last_updated": datetime(
                2023, 10, 1, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC")
            ).isoformat(),
        }

    @pytest.fixture
    def evse(self):
        CredentialsRoleFactory(country_code="NL", party_id="TST", role="EMSP")
        location = LocationFactory(
            ocpi_master__country_code="DE",
            ocpi_master__party_id="TST",
        )
        evse = EvseFactory(
            location=location,
            status=Evse.AVAILABLE,
            last_updated=datetime(2023, 10, 1, 12, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
        )
        return evse

    @pytest.mark.parametrize(
        "status,expected_status",
        [
            ("AVAILABLE", Evse.AVAILABLE),
            ("PREPARING", Evse.AVAILABLE),
            ("CHARGING", Evse.CHARGING),
            ("SUSPENDEDEV", Evse.CHARGING),
            ("SUSPENDEDEVSE", Evse.CHARGING),
            ("FINISHING", Evse.CHARGING),
            ("RESERVED", Evse.RESERVED),
            ("FAULTED", Evse.OUTOFORDER),
            ("UNAVAILABLE", Evse.CHARGING),
        ],
    )
    def test_ocpp_to_evse_status_converts_accordingly(self, status, expected_status):
        assert EvseServices.ocpp_to_evse_status(status) == expected_status

    def test_ocpp_to_evse_status_raises(self):
        with pytest.raises(ValueError):
            EvseServices.ocpp_to_evse_status("INVALID")

    @pytest.mark.django_db
    @responses.activate
    @override_settings(ENABLE_HUBJECT=True)
    def test_send_status_updates_successfully(self, evse_patch_payload, evse):
        with (
            patch(
                "ocpi22.ocpi.util.OcpiModule.send_all_updates"
            ) as mock_send_ocpi_request,
            patch(
                "ocpi22.tasks.send_hubject_request.delay"
            ) as mock_send_hubject_request,
            patch("ocpi22.tasks.send_ocpi_request.request.is_eager", False),
        ):
            EvseServices.send_status_updates(evse)

            assert evse.status == evse_patch_payload["status"]
            assert (
                evse.last_updated.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).isoformat()
                == evse_patch_payload["last_updated"]
            )

            mock_send_ocpi_request.assert_called_once()
            args = mock_send_ocpi_request.call_args[1]

            ocpi_master = evse.location.ocpi_master

            assert args.get("data") == evse_patch_payload
            assert args.get("method") == "patch"
            assert args.get("path_components") == [
                "DE",
                "TST",
                evse.location.uid,
                evse.uid,
            ]

            assert mock_send_hubject_request.call_count == 1
            call_args = mock_send_hubject_request.call_args[0][0]

            assert call_args == {
                "ActionType": "update",
                "OperatorEvseStatus": {
                    "EvseStatusRecord": [
                        {
                            "EvseID": f"{evse.evse_id}",
                            "EvseStatus": "Available",
                        },
                    ],
                    "OperatorID": "DE*TST",
                    "OperatorName": f"{ocpi_master.business_details.name}",
                },
            }

    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=True)
    def test_send_status_updates_with_naive_timezone_converts_the_timezone_to_utc(
        self, evse
    ):
        evse.last_updated = datetime(2023, 12, 25, 15, 30, 45)
        evse.status = "CHARGING"

        expected_data = {
            "status": "CHARGING",
            "last_updated": "2023-12-25T15:30:45+00:00",
        }

        with patch(
            "ocpi22.ocpi.util.OcpiModule.send_all_updates"
        ) as mock_send_all_updates:
            EvseServices.send_status_updates(evse)

            mock_send_all_updates.assert_called_once_with(
                data=expected_data,
                method="patch",
                path_components=["DE", "TST", evse.location.uid, evse.uid],
            )

    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=True)
    def test_send_status_for_not_allowed_location_does_not_call_background_update(
        self, evse_patch_payload, evse, hubject_credentials
    ):
        role = CredentialsRoleFactory(country_code="DE", party_id="TST", role="EMSP")
        role.credentials.allowed_locations = ["some_other_location_uid"]
        role.credentials.save()

        hubject_credentials.allowed_locations = ["some_other_location_uid"]
        hubject_credentials.save()

        with (
            patch(
                "ocpi22.ocpi.util.OcpiModule.send_background_update"
            ) as mock_send_background_update,
            patch(
                "integrations.hubject.services.HubjectService.post_eroaming_push_evse_status"
            ) as mock_post_eroaming_push_evse_status,
            patch(
                "ocpi22.credentials.util.find_endpoints_by_roles"
            ) as mock_find_endpoints,
        ):
            mock_find_endpoints.return_value = [
                (
                    "https://example.com/ocpi/emsp",
                    "dGVzdF9iYXNlNjQ=",
                    "DE",
                    "TST",
                    role.credentials,
                )
            ]
            EvseServices.send_status_updates(evse)

            assert evse.status == evse_patch_payload["status"]
            assert (
                evse.last_updated.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).isoformat()
                == evse_patch_payload["last_updated"]
            )

            mock_send_background_update.assert_not_called()
            mock_post_eroaming_push_evse_status.assert_not_called()

    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=True)
    def test_send_status_for_allowed_location_call_background_update(
        self, evse_patch_payload, evse, hubject_credentials
    ):
        role = CredentialsRoleFactory(country_code="DE", party_id="TST", role="EMSP")
        role.credentials.allowed_locations = [
            "some_other_location_uid",
            evse.location.uid,
        ]
        role.credentials.save()

        hubject_credentials.allowed_locations = [
            "some_other_location_uid",
            evse.location.uid,
        ]
        hubject_credentials.save()

        with (
            patch(
                "ocpi22.ocpi.util.OcpiModule.send_background_update"
            ) as mock_send_background_update,
            patch(
                "integrations.hubject.services.HubjectService.post_eroaming_push_evse_status"
            ) as mock_post_eroaming_push_evse_status,
            patch(
                "ocpi22.credentials.util.find_endpoints_by_roles"
            ) as mock_find_endpoints,
        ):
            mock_find_endpoints.return_value = [
                (
                    "https://example.com/ocpi/emsp",
                    "dGVzdF9iYXNlNjQ=",
                    "DE",
                    "TST",
                    role.credentials,
                )
            ]
            EvseServices.send_status_updates(evse)

            assert evse.status == evse_patch_payload["status"]
            assert (
                evse.last_updated.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).isoformat()
                == evse_patch_payload["last_updated"]
            )

            mock_send_background_update.assert_called_once()
            mock_post_eroaming_push_evse_status.assert_called_once()

    @pytest.mark.django_db
    @override_settings(ENABLE_HUBJECT=True)
    def test_send_status_for_empty_allowed_location_list_call_background_update(
        self, evse_patch_payload, evse, hubject_credentials
    ):
        role = CredentialsRoleFactory(country_code="DE", party_id="TST", role="EMSP")

        with (
            patch(
                "ocpi22.ocpi.util.OcpiModule.send_background_update"
            ) as mock_send_background_update,
            patch(
                "integrations.hubject.services.HubjectService.post_eroaming_push_evse_status"
            ) as mock_post_eroaming_push_evse_status,
            patch(
                "ocpi22.credentials.util.find_endpoints_by_roles"
            ) as mock_find_endpoints,
        ):
            mock_find_endpoints.return_value = [
                (
                    "https://example.com/ocpi/emsp",
                    "dGVzdF9iYXNlNjQ=",
                    "DE",
                    "TST",
                    role.credentials,
                )
            ]
            EvseServices.send_status_updates(evse)

            assert evse.status == evse_patch_payload["status"]
            assert (
                evse.last_updated.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).isoformat()
                == evse_patch_payload["last_updated"]
            )

            mock_send_background_update.assert_called_once()
            mock_post_eroaming_push_evse_status.assert_called_once()
