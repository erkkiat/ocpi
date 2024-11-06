import pytest

from ocpi22.locations.services import EvseServices
from ocpi22.models.location import Evse


class TestEvseServices:
    @pytest.mark.parametrize("status,expected_status",
                             [("AVAILABLE", Evse.AVAILABLE),
                              ("PREPARING", Evse.CHARGING),
                              ("CHARGING", Evse.CHARGING),
                              ("SUSPENDEDEV", Evse.CHARGING),
                              ("SUSPENDEDEVSE", Evse.CHARGING),
                              ("FINISHING", Evse.CHARGING),
                              ("RESERVED", Evse.RESERVED),
                              ("FAULTED", Evse.OUTOFORDER),
                              ("UNAVAILABLE", Evse.CHARGING),
                              ])
    def test_ocpp_to_evse_status_converts_accordingly(self, status, expected_status):
        assert EvseServices.ocpp_to_evse_status(status) == expected_status

    def test_ocpp_to_evse_status_raises(self):
        with pytest.raises(ValueError):
            EvseServices.ocpp_to_evse_status("INVALID")


