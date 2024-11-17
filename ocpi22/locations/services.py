# TODO refactor this to have ddomain speicific services
from ocpi22.models.location import Evse


class EvseServices:
    @staticmethod
    def ocpp_to_evse_status(status: str):
        match status:
            case "AVAILABLE":
                return Evse.AVAILABLE
            case "PREPARING":
                return Evse.CHARGING
            case "CHARGING":
                return Evse.CHARGING
            case "SUSPENDEDEV":
                return Evse.CHARGING
            case "SUSPENDEDEVSE":
                return Evse.CHARGING
            case "FINISHING":
                return Evse.CHARGING
            case "RESERVED":
                return Evse.RESERVED
            case "FAULTED":
                return Evse.OUTOFORDER
            case "UNAVAILABLE":
                return Evse.CHARGING
            case _:
                raise ValueError(f"Invalid OCPP status [{status}] found")
