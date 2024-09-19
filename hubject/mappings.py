import re

from typing import List

from hubject.models import ERoamingPushEvseData, EvseDataRecord, EvseID, Address, GeoCoordinates, OperatorEvseData, \
    ActionType, Plug, ChargingFacility, PowerType, AuthenticationMode, \
    ValueAddedService, AccessibilityLocation, Accessibility, DecimalDegree, \
    CalibrationLawDataAvailability, DynamicInfoAvailable
from ocpi22.choices import OCPICapabilityEnum
from ocpiconnector import settings
from ocpi22.models.location import Location, Connector
from rest_framework.exceptions import ValidationError

def map_location_to_eroaming_push_evse_data(location: Location) -> ERoamingPushEvseData:
    evse_data_records = []
    for evse in location.evses.all():
        address_info = split_address_into_street_and_house_number(location.address)
        evse_data_record = EvseDataRecord(
            EvseID=EvseID(evse.evse_id),
            Address=Address(
                Country=location.country,
                City=location.city,
                Street=address_info.get('street', '-'),
                PostalCode=location.postal_code,
                HouseNum=address_info.get('house', '-'),
                # todo : Floor missing in ocpi22,
                # todo : Region missing in ocpi22,
                ParkingFacility= True if location.parking_type else False,
                # todo : ParkingSpot missing in ocpi22,
                TimeZone= location.time_zone
            ),
            GeoCoordinates=GeoCoordinates(
                Google=None,
                DecimalDegree=DecimalDegree(
                    Latitude= str(location.latitude),
                    Longitude=str(location.longitude)
                ),
                DegreeMinuteSeconds=None
            ),
            Plugs=get_distinct_plugs_from_connector_std_choices(evse.connectors.all()),
            ChargingFacilities=get_all_charging_facilities_from_connectors(evse.connectors.all()),
            # todo : RenewableEnergy check with smappee, default to False
            RenewableEnergy=False,
            # todo : EnergySource missing in ocpi22 location model, But it can be found in OCPIEnergyMix, is not clearly mapping directly to OICP
            # todo : EnvironmentalImpact missing in ocpi22, But it can be found in OCPIEnergyMix, is not clearly mapping directly to OICP
            # todo : CalibrationLawDataAvailability missing in ocpi22, required, defaulted to Local
            CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
            AuthenticationModes=get_all_authentication_modes_from_capabilities(evse.capabilities),

            # todo : MaxCapacity missing in ocpi22,
            # todo : PaymentOptions missing in ocpi22,
            PaymentOptions=[],
            ValueAddedServices=get_all_value_added_services_from_capabilities(evse.capabilities),
            # todo : Accessibility missing in ocpi22, default to free, discuss with smappee
            Accessibility=Accessibility.Free_publicly_accessible,
            AccessibilityLocation=map_parking_types_to_accessibility_locations(location.parking_type),

            # todo : HotlinePhoneNumber missing in ocpi22, we have msp phone not CPO.
            HotlinePhoneNumber=settings.HOTLINE,
            # todo : AdditionalInfo missing in ocpi22,

            # todo : ChargingStationLocationReference missing in ocpi22,
            # todo : ChargingStationNames missing in ocpi22
            ChargingStationNames=[],
            GeoChargingPointEntrance= GeoCoordinates(
                Google=None,
                DecimalDegree=DecimalDegree(
                    Latitude= str(location.latitude),
                    Longitude=str(location.longitude)
                ),
                DegreeMinuteSeconds=None
            ),
            # todo : IsOpen24Hours usage of the charging when closed does not directly map to OCIP,
            IsOpen24Hours=location.charging_when_closed,
            # todo : OpeningTimes missing in ocpi22,
            OpeningTimes=None,
            
            # todo : HubOperatorID missing in ocpi22,
            # todo : ClearinghouseID missing in ocpi22,
            # todo : IsHubjectCompatible missing in ocpi22, used a default value True
            IsHubjectCompatible=True,
            # todo : DynamicInfoAvailable missing in ocpi22, required, Default to True
            DynamicInfoAvailable=DynamicInfoAvailable.true,
        )
        evse_data_records.append(evse_data_record)

    operator_evse_data = OperatorEvseData(
        OperatorID= location.party(),
        OperatorName=location.owner.name,
        EvseDataRecord=evse_data_records
    )

    eroaming_push_evse_data = ERoamingPushEvseData(
        # todo : Action missing in ocpi22, required, defaulted to insert
        ActionType=ActionType.insert,
        OperatorEvseData=operator_evse_data
    )

    return eroaming_push_evse_data


def map_connector_std_choices_to_plug(connector_std: str) -> Plug:
    """
    >>> map_connector_std_choices_to_plug('IEC_62196_T2')
    <Plug.Type_2_Outlet: 'Type 2 Outlet'>
    >>> map_connector_std_choices_to_plug('CHADEMO')
    <Plug.CHAdeMO: 'CHAdeMO'>
    >>> map_connector_std_choices_to_plug('TESLA_S')
    <Plug.Tesla_Connector: 'Tesla Connector'>

    @param connector_std: OCPI 2.2.1 Connector Standard Choice
    @return: Corresponding Plug enum for the given connector standard choice
    """
    mapping = {
        'IEC_62196_T2': Plug.Type_2_Outlet,
        'IEC_62196_T2_COMBO': Plug.Type_2_Outlet,
        'CHADEMO': Plug.CHAdeMO,
        'IEC_62196_T1': Plug.Type_1_Connector__Cable_Attached_,
        'IEC_62196_T1_COMBO': Plug.CCS_Combo_1_Plug__Cable_Attached_,
        'IEC_62196_T3A': Plug.Type_3_Outlet,
        'IEC_62196_T3C': Plug.Type_3_Outlet,
        'DOMESTIC_F': Plug.Type_F_Schuko,
        'DOMESTIC_G': Plug.Type_G_British_Standard,
        'DOMESTIC_J': Plug.Type_J_Swiss_Standard,
        'IEC_60309_2_single_16': Plug.IEC_60309_Single_Phase,
        'IEC_60309_2_three_16': Plug.IEC_60309_Single_Phase,
        'IEC_60309_2_three_32': Plug.IEC_60309_Three_Phase,
        'IEC_60309_2_three_64': Plug.IEC_60309_Three_Phase,
        'TESLA_S': Plug.Tesla_Connector,
    }.get(connector_std.upper(), None)
    if not mapping:
        raise ValidationError(f"'{connector_std}' is not a known STANDARD Choice.")
    return mapping

def get_distinct_plugs_from_connector_std_choices(connectors: List[Connector]) -> List[Plug]:
    plugs = {map_connector_std_choices_to_plug(connector.standard) for connector in connectors}
    return list(plugs)

def map_power_type_choices_221_to_power_type(power_type_choice_221: str) -> PowerType:
    """
    >>> map_power_type_choices_221_to_power_type('AC_1_PHASE')
    <PowerType.AC_1_PHASE: 'AC_1_PHASE'>
    >>> map_power_type_choices_221_to_power_type('DC')
    <PowerType.DC: 'DC'>

    @param power_type_choice_221: OCPI 2.2.1 PowerType Choice
    @return: Corresponding Plug enum for the given power type choice
    """
    mapping = {
        'AC_1_PHASE': PowerType.AC_1_PHASE,
        'AC_3_PHASE': PowerType.AC_3_PHASE,
        'DC': PowerType.DC,
    }.get(power_type_choice_221.upper())
    if not mapping:
        raise ValidationError(f"'{power_type_choice_221}' is not a known POWERTYPE_221 Choice.")
    return mapping

def get_all_charging_facilities_from_connectors(connectors: List[Connector]) -> List[ChargingFacility]:
    return [
        ChargingFacility(
            PowerType=map_power_type_choices_221_to_power_type(connector.power_type[0]),
            Voltage=connector.max_voltage,
            Amperage=connector.max_amperage,
            Power=connector.max_electric_power
        )
        for connector in connectors
    ]


address_patterns = [
    re.compile(r'(?P<street>[^\d]+)\s(?P<house>\d+)'),  # Belgium
    re.compile(r'(?P<street>[^\d]+)\s(?P<house>\d+)'),  # Netherlands
    re.compile(r'(?P<street>[^\d]+)\s(?P<house>\d+)'),  # France
    re.compile(r'(?P<street>[^\d]+)\s(?P<house>\d+)')   # Germany
]

def split_address_into_street_and_house_number(address: str) -> dict[str, str]:
    """
    >>> split_address_into_street_and_house_number("Oulu 1")
    {'street': 'Oulu', 'house': '1'}
    >>> split_address_into_street_and_house_number("Weteringstraat 34-1, 1017 SP Amsterdam, NLD")
    {'street': 'Weteringstraat', 'house': '34'}
    >>> split_address_into_street_and_house_number("Mme Marie PAGE, 23 Rue de Grenelle, 75700 PARIS CEDEX, France")
    {'street': 'Mme Marie PAGE,', 'house': '23'}
    >>> split_address_into_street_and_house_number("Mrs F Meier, Weberstr. 2, 53113 BONN 1, Germany")
    {'street': 'Mrs F Meier, Weberstr.', 'house': '2'}
    >>> split_address_into_street_and_house_number("Alfred Nobellaan 22 App 150Z, 2660 Antwerpen, BEL")
    {'street': 'Alfred Nobellaan', 'house': '22'}
    >>> split_address_into_street_and_house_number("Kandintie E 4, 00430 Helsinki, FIN")
    {'street': 'Kandintie E', 'house': '4'}
    """
    for pattern in address_patterns:
        match = pattern.search(address)
        if match:
            result = {k: v.strip() for k, v in match.groupdict().items() if v}
            return result
    return {'street': '-', 'house': '-'}

def map_capability_to_authentication_mode(capability: OCPICapabilityEnum) -> AuthenticationMode:
    """
    >>> map_capability_to_authentication_mode(OCPICapabilityEnum.RFID_READER)
    <AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>
    """

    return {
        OCPICapabilityEnum.RFID_READER: AuthenticationMode.NFC_RFID_Classic,
    }.get(capability, None)

def get_all_authentication_modes_from_capabilities(capabilities: List[OCPICapabilityEnum]) -> list[AuthenticationMode]:
    """
    >>> get_all_authentication_modes_from_capabilities([OCPICapabilityEnum.RFID_READER])
    [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
    >>> get_all_authentication_modes_from_capabilities([OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.CREDIT_CARD_PAYABLE])
    [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
    >>> get_all_authentication_modes_from_capabilities([OCPICapabilityEnum.UNLOCK_CAPABLE])
    []
    """

    # todo : Item AuthenticationModes cannot map all modes directly to OICP
    return [mode for mode in (map_capability_to_authentication_mode(capability) for capability in capabilities) if mode]

def map_capability_to_value_added_services(capability: OCPICapabilityEnum) -> ValueAddedService:
    """
    >>> map_capability_to_value_added_services(OCPICapabilityEnum.RESERVABLE)
    <ValueAddedService.Reservation: 'Reservation'>
    """

    return {
        OCPICapabilityEnum.RESERVABLE: ValueAddedService.Reservation,
    }.get(capability, None)

def get_all_value_added_services_from_capabilities(capabilities: List[OCPICapabilityEnum]) -> list[ValueAddedService]:
    """
    >>> get_all_value_added_services_from_capabilities([OCPICapabilityEnum.CHARGING_PROFILE_CAPABLE])
    []
    >>> get_all_value_added_services_from_capabilities([OCPICapabilityEnum.RESERVABLE])
    [<ValueAddedService.Reservation: 'Reservation'>]
    """

    # todo : Item AuthenticationModes cannot map other modes directly to OICP
    return [vas for vas in (map_capability_to_value_added_services(capability) for capability in capabilities) if vas]

def map_parking_types_to_accessibility_locations(parking_type: str) -> AccessibilityLocation:
    """
    >>> map_parking_types_to_accessibility_locations('PARKING_GARAGE')
    <AccessibilityLocation.ParkingGarage: 'ParkingGarage'>
    >>> map_parking_types_to_accessibility_locations('PARKING_LOT')
    <AccessibilityLocation.ParkingLot: 'ParkingLot'>
    """

    return  {
        'PARKING_GARAGE': AccessibilityLocation.ParkingGarage,
        'PARKING_LOT': AccessibilityLocation.ParkingLot,
        'ON_STREET': AccessibilityLocation.OnStreet,
        'UNDERGROUND_GARAGE': AccessibilityLocation.UndergroundParkingGarage,
    }.get(parking_type, None)

