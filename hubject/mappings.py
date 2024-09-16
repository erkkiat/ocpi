from typing import List, Any

from hubject import models
# ERoamingPushEvseData, EvseDataRecord, EvseID, Address, GeoCoordinates, OperatorEvseData, \
#     ActionType, Plug, ChargingFacility, PowerType
from ocpi22.models.location import Location, Connector
from ocpi22.ocpi.util import Ocpi
from rest_framework.exceptions import ValidationError

def map_location_to_eroaming_push_evse_data(location: Location) -> models.ERoamingPushEvseData:
    evse_data_records = []
    for evse in location.evses:
        evse_data_record = models.EvseDataRecord(
            EvseID=models.EvseID(__root__=evse.evse_id),
            Address=models.Address(
                Country=location.country,
                City=location.city,
                Street=location.address,
                PostalCode=location.postal_code,
                # todo : HouseNum missing in ocpi22 (required),
                # todo : Floor missing in ocpi22,
                # todo : Region missing in ocpi22,
                ParkingFacility= True if location.parking_type else False,
                # todo : ParkingSpot missing in ocpi22,
                TimeZone= location.time_zone
            ),
            GeoCoordinates=models.GeoCoordinates(
                DecimalDegree=dict(
                    Longitude=location.longitude,
                    Latitude=location.latitude
                )
            ),
            Plugs=get_distinct_plugs_from_connector_std_choices(evse.connectors),
            ChargingFacilities=get_all_charging_facilities_from_connectors(evse.connectors),
            # todo : RenewableEnergy missing in ocpi22,
            # todo : EnergySource missing in ocpi22,
            # todo : EnvironmentalImpact missing in ocpi22,
            # todo : CalibrationLawDataAvailability missing in ocpi22,
            # todo : AuthenticationModes missing in ocpi22,
            # todo : MaxCapacity missing in ocpi22,
            # todo : PaymentOptions missing in ocpi22,
            # todo : ValueAddedServices missing in ocpi22,

            # todo : Accessibility missing in ocpi22,
            # todo : AccessibilityLocation missing in ocpi22,

            # todo : HotlinePhoneNumber missing in ocpi22,
            # todo : AdditionalInfo missing in ocpi22,
            # todo : ChargingStationLocationReference missing in ocpi22,
            # todo : GeoChargingPointEntrance missing in ocpi22,
            # todo : IsOpen24Hours missing in ocpi22,
            # todo : OpeningTimes missing in ocpi22,
            # todo : HubOperatorID missing in ocpi22,
            # todo : ClearinghouseID missing in ocpi22,
            # todo : IsHubjectCompatible missing in ocpi22,
            # todo : DynamicInfoAvailable missing in ocpi22
        )
        evse_data_records.append(evse_data_record)

    operator_evse_data = models.OperatorEvseData(
        OperatorID= location.party(),
        # OperatorName=,
        EvseDataRecord=evse_data_records
    )

    eroaming_push_evse_data = models.ERoamingPushEvseData(
        ActionType=models.ActionType.insert,
        OperatorEvseData=operator_evse_data
    )

    return eroaming_push_evse_data

# def map_eroaming_push_evse_data_to_location(eroaming_data: ERoamingPushEvseData) -> Location:
#     operator_data = eroaming_data.OperatorEvseData
#     evse_data_records = operator_data.EvseDataRecord
#
#     # Assuming the first EVSE data record for simplicity
#     first_evse_data = evse_data_records[0]
#
#     location = Location(
#         uid=operator_data.OperatorID,
#         name=operator_data.OperatorName,
#         address=first_evse_data.Address.Street,
#         city=first_evse_data.Address.City,
#         postal_code=first_evse_data.Address.PostalCode,
#         country=first_evse_data.Address.Country,
#         coordinates=f"{first_evse_data.GeoCoordinates.DecimalDegree['Longitude']},{first_evse_data.GeoCoordinates.DecimalDegree['Latitude']}",
#         evses=[{
#             'uid': evse.EvseID.__root__,
#             'house_num': evse.Address.HouseNum,
#             'floor': evse.Address.Floor,
#             'region': evse.Address.Region,
#             'parking_facility': evse.Address.ParkingFacility,
#             'parking_spot': evse.Address.ParkingSpot,
#             'time_zone': evse.Address.TimeZone,
#             'plugs': evse.Plugs,
#             'charging_facilities': evse.ChargingFacilities,
#             'renewable_energy': evse.RenewableEnergy,
#             'energy_source': evse.EnergySource,
#             'environmental_impact': evse.EnvironmentalImpact,
#             'calibration_law_data_availability': evse.CalibrationLawDataAvailability,
#             'authentication_modes': evse.AuthenticationModes,
#             'max_capacity': evse.MaxCapacity,
#             'payment_options': evse.PaymentOptions,
#             'value_added_services': evse.ValueAddedServices,
#             'accessibility': evse.Accessibility,
#             'accessibility_location': evse.AccessibilityLocation,
#             'hotline_phone_number': evse.HotlinePhoneNumber,
#             'additional_info': evse.AdditionalInfo,
#             'charging_station_location_reference': evse.ChargingStationLocationReference,
#             'geo_charging_point_entrance': evse.GeoChargingPointEntrance,
#             'is_open_24_hours': evse.IsOpen24Hours,
#             'opening_times': evse.OpeningTimes,
#             'hub_operator_id': evse.HubOperatorID,
#             'clearinghouse_id': evse.ClearinghouseID,
#             'is_hubject_compatible': evse.IsHubjectCompatible,
#             'dynamic_info_available': evse.DynamicInfoAvailable
#         } for evse in evse_data_records]
#     )
#
#     return location


def map_connector_std_choices_to_plug(connector_std: str) -> models.Plug:
    mapping = {
        'IEC_62196_T2': models.Plug.Type_2_Outlet,
        'IEC_62196_T2_COMBO': models.Plug.Type_2_Outlet,
        'CHADEMO': models.Plug.CHAdeMO,
        'IEC_62196_T1': models.Plug.Type_1_Connector__Cable_Attached_,
        'IEC_62196_T1_COMBO': models.Plug.CCS_Combo_1_Plug__Cable_Attached_,
        'IEC_62196_T3A': models.Plug.Type_3_Outlet,
        'IEC_62196_T3C': models.Plug.Type_3_Outlet,
        # 'DOMESTIC_A': Plug.Type_2_Outlet,
        # 'DOMESTIC_B': Plug.Type_2_Outlet,
        # 'DOMESTIC_C': Plug.Type_2_Outlet,
        # 'DOMESTIC_D': Plug.Type_2_Outlet,
        # 'DOMESTIC_E': Plug.Type_2_Outlet,
        'DOMESTIC_F': models.Plug.Type_F_Schuko,
        'DOMESTIC_G': models.Plug.Type_G_British_Standard,
        # 'DOMESTIC_H': Plug.Type_2_Outlet,
        # 'DOMESTIC_I': Plug.Type_2_Outlet,
        'DOMESTIC_J': models.Plug.Type_J_Swiss_Standard,
        # 'DOMESTIC_K': Plug.Type_2_Outlet,
        # 'DOMESTIC_L': Plug.Type_2_Outlet,
        'IEC_60309_2_single_16': models.Plug.IEC_60309_Single_Phase,
        'IEC_60309_2_three_16': models.Plug.IEC_60309_Single_Phase,
        'IEC_60309_2_three_32': models.Plug.IEC_60309_Three_Phase,
        'IEC_60309_2_three_64': models.Plug.IEC_60309_Three_Phase,
        # 'PANTOGRAPH_BOTTOM_UP': Plug.Type_2_Outlet,
        # 'PANTOGRAPH_TOP_DOWN': Plug.Type_2_Outlet,
        'TESLA_S': models.Plug.Tesla_Connector,
    }.get(connector_std.upper(), None)
    if not mapping:
        raise ValidationError(f"'{connector_std}' is not a known STANDARD Choice.")
    return mapping

def get_distinct_plugs_from_connector_std_choices(connectors: List[Connector]) -> List[models.Plug]:
    plugs = {map_connector_std_choices_to_plug(connector.standard) for connector in connectors}
    return list(plugs)

def map_power_type_choices_221_to_power_type(power_type_choice_221: str) -> models.PowerType:
    mapping = {
        'AC_1_PHASE': models.PowerType.AC_1_PHASE,
        'AC_3_PHASE': models.PowerType.AC_3_PHASE,
        'DC': models.PowerType.DC,
    }.get(power_type_choice_221.upper())
    if not mapping:
        raise ValidationError(f"'{power_type_choice_221}' is not a known POWERTYPE_221 Choice.")
    return mapping

def get_all_charging_facilities_from_connectors(connectors: List[Connector]) -> List[models.ChargingFacility]:
    return [
        models.ChargingFacility(
            PowerType=map_power_type_choices_221_to_power_type(connector.power_type[0]),
            Voltage=connector.max_voltage,
            Amperage=connector.max_amperage,
            Power=connector.max_electric_power
        )
        for connector in connectors
    ]

def get_housenumber_from_address(address: models.Address) -> str:
    # todo : identify the address format.
    pass
