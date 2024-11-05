# TODO refactor this to have ddomain speicific services
from ocpi22.choices import OcppStatusChoices
from ocpi22.models.location import Evse


def ocpp_to_evse_statu(status: str):
    match status:
        case "AVAILABLE":
            return Evse.STATUS_CHOICES.AVAILABLE
        case "PREPARING":
            return Evse.STATUS_CHOICES.CHARGING
        case "CHARGING":
            return Evse.STATUS_CHOICES.HARGING
        case "SUSPENDEDEV":
            return Evse.STATUS_CHOICES.CHARGING
        case "SUSPENDEDEVSE":
            return Evse.STATUS_CHOICES.CHARGING
        case "FINISHING":
            return Evse.STATUS_CHOICES.CHARGING
        case "RESERVED":
            return Evse.STATUS_CHOICES.RESERVED
        case "FAULTED":
            return Evse.STATUS_CHOICES.OUT_OF_ORDER
        case "UNAVAILABLE":
            return Evse.STATUS_CHOICES.CHARGING
        case _:
            raise ValueError(f"Invalid OCPP status [{status}] found")