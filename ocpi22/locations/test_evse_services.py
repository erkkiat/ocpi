import json
import zoneinfo
from datetime import datetime
from unittest.mock import patch

import pytest
import responses

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
            ("PREPARING", Evse.CHARGING),
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
    def test_send_status_updates_successfully(self, evse_patch_payload, evse):
        with (
            patch(
                "ocpi22.tasks.send_ocpi_request.apply_async"
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
            call_args = mock_send_ocpi_request.call_args[0][0]
            actual_data = json.loads(call_args[0])

            ocpi_master = evse.location.ocpi_master

            assert actual_data == evse_patch_payload
            # How are we able to send updates of someone else location. Should we restrict this?
            assert (
                call_args[1]
                == f"https://localhost/ocpi/locations/{ocpi_master.country_code}/{ocpi_master.party_id}/{evse.location.uid}/{evse.uid}"
            )
            assert call_args[3:8] == ("NL", "TST", "FI", "CPO", "patch")

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
