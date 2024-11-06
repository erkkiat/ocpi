import pytest

from ocpi22.locations.services import EvseServices
from ocpi22.models.location import Evse


class TestEvseServices:
    @pytest.mark.parametrize("status,expected_status",
                             [("AVAILABLE", Evse.STATUS_CHOICES.AVAILABLE),
                              ("PREPARING", Evse.STATUS_CHOICES.CHARGING),
                              ("CHARGING", Evse.STATUS_CHOICES.CHARGING),
                              ("SUSPENDEDEV", Evse.STATUS_CHOICES.CHARGING),
                              ("SUSPENDEDEVSE", Evse.STATUS_CHOICES.CHARGING),
                              ("FINISHING", Evse.STATUS_CHOICES.CHARGING),
                              ("RESERVED", Evse.STATUS_CHOICES.RESERVED),
                              ("FAULTED", Evse.STATUS_CHOICES.OUT_OF_ORDER),
                              ("UNAVAILABLE", Evse.STATUS_CHOICES.CHARGING),
                              ])
    def test_ocpp_to_evse_status_converts_accordingly(self, status, expected_status):
        assert EvseServices.ocpp_to_evse_status(status) == expected_status

    def test_ocpp_to_evse_status_raises(self):
        with pytest.raises(ValueError):
            EvseServices.ocpp_to_evse_status("INVALID")


