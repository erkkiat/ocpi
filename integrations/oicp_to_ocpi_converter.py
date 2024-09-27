import re
from datetime import datetime
from typing import List

import pytz
from django.conf import settings
from django.core.exceptions import ValidationError

from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    OperatorEvseData,
    EvseDataRecord,
    Plug,
    EvseID,
    Address,
    GeoCoordinates,
    DecimalDegree,
    CalibrationLawDataAvailability,
    Accessibility,
    InfoTextType,
    DynamicInfoAvailable,
    PowerType,
    ChargingFacility,
    AuthenticationMode,
    ValueAddedService,
    AccessibilityLocation,
    PaymentOption,
)
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.location import Location, Evse, Connector


class OCPIToOICPConverter:
    def __init__(self, oicp_version: str, ocpi_version: str):
        self.oicp_version = oicp_version
        self.ocpi_version = ocpi_version
        self.address_pattern = re.compile(r"(?P<street>[^\d]+)\s(?P<house>\d+)")

    def convert_to_operator_evse_data(self, location: Location) -> OperatorEvseData:
        return OperatorEvseData(
            OperatorID=location.party(),
            OperatorName=location.owner.name,
            EvseDataRecord=[
                self._convert_to_evse_data_record(evse, location)
                for evse in location.evses.all()
            ],
        )

    def _convert_to_evse_data_record(
        self, evse: Evse, location: Location
    ) -> EvseDataRecord:
        return EvseDataRecord(
            # todo : deltaType missing in ocpi22
            deltaType=None,
            lastUpdate=evse.last_updated,
            EvseID=EvseID(evse.evse_id),
            # todo : ChargingPoolID missing in ocpi22
            ChargingPoolID=None,
            # todo : ChargingStationID missing in ocpi22
            ChargingStationId=None,
            # todo : HardwareManufacturer missing in ocpi22
            HardwareManufacturer=None,
            # todo : ChargingStationImage missing in ocpi22
            ChargingStationImage=None,
            # todo : SubOperatorName missing in ocpi22
            SubOperatorName=None,
            Address=Address(
                Country=location.country,
                City=location.city,
                Street=self.get_street(location.address),
                PostalCode=location.postal_code,
                HouseNum=self.get_house_number(location.address),
                # todo : Floor missing in ocpi22,
                # todo : Region missing in ocpi22,
                ParkingFacility=True if location.parking_type else False,
                # todo : ParkingSpot missing in ocpi22,
                TimeZone=self.get_timezone(location.time_zone),
            ),
            GeoCoordinates=GeoCoordinates(
                Google=None,
                DecimalDegree=DecimalDegree(
                    Latitude=str(location.latitude), Longitude=str(location.longitude)
                ),
                DegreeMinuteSeconds=None,
            ),
            Plugs=self.get_distinct_plugs(evse.connectors.all()),
            DynamicPowerLevel=None,
            ChargingFacilities=self.get_all_charging_facilities(evse.connectors.all()),
            # todo : RenewableEnergy check with smappee, default to False
            RenewableEnergy=False,
            # todo : EnergySource missing in ocpi22 location model, But it can be found in OCPIEnergyMix, is not clearly mapping directly to OICP
            EnergySource=None,
            # todo : EnvironmentalImpact missing in ocpi22, But it can be found in OCPIEnergyMix, is not clearly mapping directly to OICP
            EnvironmentalImpact=None,
            # todo : CalibrationLawDataAvailability missing in ocpi22, required, defaulted to Local
            CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
            AuthenticationModes=self.get_all_authentication_modes(evse.capabilities),
            # todo : MaxCapacity missing in ocpi22,
            MaxCapacity=None,
            # todo : PaymentOptions missing in ocpi22,
            PaymentOptions=self.get_payment_options(evse.capabilities),
            ValueAddedServices=self.get_all_value_added_services(evse.capabilities),
            # todo : Accessibility missing in ocpi22, default to free, discuss with smappee
            Accessibility=Accessibility.Free_publicly_accessible,
            AccessibilityLocation=self.map_ocpi_parking_types_to_accessibility_locations(
                location.parking_type
            ),
            # todo : HotlinePhoneNumber missing in ocpi22, we have msp phone not CPO.
            HotlinePhoneNumber=settings.HOTLINE,
            # todo : AdditionalInfo missing in ocpi22,
            # todo : ChargingStationLocationReference missing in ocpi22,
            # todo : ChargingStationNames missing in ocpi22
            ChargingStationNames=[InfoTextType(lang="en", value=location.name)],
            GeoChargingPointEntrance=GeoCoordinates(
                Google=None,
                DecimalDegree=DecimalDegree(
                    Latitude=str(location.latitude), Longitude=str(location.longitude)
                ),
                DegreeMinuteSeconds=None,
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

    def convert(self): ...

    def construct_ocpi_format(self) -> List[ERoamingPushEvseData]: ...

    def map_connector_to_plug(self, connector_std: str) -> Plug:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.map_connector_to_plug('IEC_62196_T2')
        <Plug.Type_2_Outlet: 'Type 2 Outlet'>
        >>> oicp_converter.map_connector_to_plug('CHADEMO')
        <Plug.CHAdeMO: 'CHAdeMO'>
        >>> oicp_converter.map_connector_to_plug('TESLA_S')
        <Plug.Tesla_Connector: 'Tesla Connector'>

        @param connector_std: OCPI 2.2.1 Connector Standard, This describes the connector standard/type, e.g. CHADEMO, Tesla, etc.
        @return: Corresponding Plug enum for the given connector standard/type choice
        """
        mapping = {
            "IEC_62196_T2": Plug.Type_2_Outlet,
            "IEC_62196_T2_COMBO": Plug.CCS_Combo_2_Plug__Cable_Attached_,
            "CHADEMO": Plug.CHAdeMO,
            "IEC_62196_T1": Plug.Type_1_Connector__Cable_Attached_,
            "IEC_62196_T1_COMBO": Plug.CCS_Combo_1_Plug__Cable_Attached_,
            "IEC_62196_T3A": Plug.Type_3_Outlet,
            "IEC_62196_T3C": Plug.Type_3_Outlet,
            "DOMESTIC_F": Plug.Type_F_Schuko,
            "DOMESTIC_G": Plug.Type_G_British_Standard,
            "DOMESTIC_J": Plug.Type_J_Swiss_Standard,
            "IEC_60309_2_single_16": Plug.IEC_60309_Single_Phase,
            "IEC_60309_2_three_16": Plug.IEC_60309_Three_Phase,
            "IEC_60309_2_three_32": Plug.IEC_60309_Three_Phase,
            "IEC_60309_2_three_64": Plug.IEC_60309_Three_Phase,
            "TESLA_S": Plug.Tesla_Connector,
        }.get(connector_std.upper(), None)
        if not mapping:
            raise ValidationError(f"'{connector_std}' is not a known connector type.")
        return mapping

    def get_distinct_plugs(self, connectors: List[Connector]) -> List[Plug]:
        """
        This function collects only the distinct plugs from the given list of OCPI 2.2.1 Connectors.
        @param connectors: List of OCPI 2.2.1 Connectors
        @return: List of corresponding Plug enums
        """
        plugs = {
            self.map_connector_to_plug(connector.standard) for connector in connectors
        }
        return list(plugs)

    def map_power_type_choices_221_to_power_type(
        self, power_type_choice_221: str
    ) -> PowerType:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.map_power_type_choices_221_to_power_type('AC_1_PHASE')
        <PowerType.AC_1_PHASE: 'AC_1_PHASE'>
        >>> oicp_converter.map_power_type_choices_221_to_power_type('DC')
        <PowerType.DC: 'DC'>

        @param power_type_choice_221: OCPI 2.2.1 PowerType Choice
        @return: Corresponding Plug enum for the given power type choice
        """
        mapping = {
            "AC_1_PHASE": PowerType.AC_1_PHASE,
            "AC_3_PHASE": PowerType.AC_3_PHASE,
            "DC": PowerType.DC,
        }.get(power_type_choice_221.upper())
        if not mapping:
            raise ValidationError(
                f"'{power_type_choice_221}' is not a known POWERTYPE_221."
            )
        return mapping

    def get_all_charging_facilities(
        self, connectors: List[Connector]
    ) -> List[ChargingFacility]:
        return [
            ChargingFacility(
                PowerType=self.map_power_type_choices_221_to_power_type(
                    connector.power_type
                ),
                Voltage=connector.max_voltage,
                Amperage=connector.max_amperage,
                Power=connector.max_electric_power,
            )
            for connector in connectors
        ]

    def get_street(self, address: str) -> str:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.get_street("Oulu 1")
        'Oulu'
        >>> oicp_converter.get_street("Weteringstraat 34-1, 1017 SP Amsterdam")
        'Weteringstraat'
        >>> oicp_converter.get_street("Mme Marie PAGE, 23 Rue de Grenelle, 75700 PARIS CEDEX, France")
        'Mme Marie PAGE,'
        >>> oicp_converter.get_street("Mrs F Meier, Weberstr. 2, 53113 BONN 1")
        'Mrs F Meier, Weberstr.'
        >>> oicp_converter.get_street("Alfred Nobellaan 22 App 150Z, 2660 Antwerpen, BEL")
        'Alfred Nobellaan'
        """
        match = self.address_pattern.search(address)
        if match:
            result = {k: v.strip() for k, v in match.groupdict().items() if v}
            return result.get("street", "-")
        return "-"

    def get_house_number(self, address: str) -> str:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.get_house_number("Oulu 1")
        '1'
        >>> oicp_converter.get_house_number("Weteringstraat 34-1, 1017 SP Amsterdam, NLD")
        '34'
        >>> oicp_converter.get_house_number("Mme Marie PAGE, 23 Rue de Grenelle, 75700 PARIS CEDEX, France")
        '23'
        >>> oicp_converter.get_house_number("Mrs F Meier, Weberstr. 2, 53113 BONN 1, Germany")
        '2'
        >>> oicp_converter.get_house_number("Alfred Nobellaan 22 App 150Z, 2660 Antwerpen, BEL")
        '22'
        >>> oicp_converter.get_house_number("Kandintie E 4, 00430 Helsinki, FIN")
        '4'
        """

        match = self.address_pattern.search(address)
        if match:
            result = {k: v.strip() for k, v in match.groupdict().items() if v}
            return result.get("house", "-")
        return "-"

    def map_capability_to_authentication_mode(
        self,
        capability: OCPICapabilityEnum,
    ) -> AuthenticationMode:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.map_capability_to_authentication_mode(OCPICapabilityEnum.RFID_READER)
        <AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>
        """

        return {
            OCPICapabilityEnum.RFID_READER: AuthenticationMode.NFC_RFID_Classic,
        }.get(capability, None)

    def get_all_authentication_modes(
        self,
        capabilities: List[OCPICapabilityEnum],
    ) -> list[AuthenticationMode]:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.get_all_authentication_modes([OCPICapabilityEnum.RFID_READER])
        [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
        >>> oicp_converter.get_all_authentication_modes([OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.CREDIT_CARD_PAYABLE])
        [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
        >>> oicp_converter.get_all_authentication_modes([OCPICapabilityEnum.UNLOCK_CAPABLE])
        []

        This function collects all of the matching AuthenticationModes for the given list of OCPI 2.2.1 Capabilities.
        @param capabilities: List of OCPI 2.2.1 Capabilities
        @return: List of corresponding AuthenticationMode enums
        """

        # todo : Item AuthenticationModes cannot map all modes directly to OICP
        return [
            mode
            for mode in (
                self.map_capability_to_authentication_mode(capability)
                for capability in capabilities
            )
            if mode
        ]

    def map_capability_to_value_added_services(
        self,
        capability: OCPICapabilityEnum,
    ) -> ValueAddedService:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.map_capability_to_value_added_services(OCPICapabilityEnum.RESERVABLE)
        <ValueAddedService.Reservation: 'Reservation'>
        """

        return {
            OCPICapabilityEnum.RESERVABLE: ValueAddedService.Reservation,
        }.get(capability, None)

    def get_all_value_added_services(
        self,
        capabilities: List[OCPICapabilityEnum],
    ) -> list[ValueAddedService]:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.get_all_value_added_services([OCPICapabilityEnum.CHARGING_PROFILE_CAPABLE])
        []
        >>> oicp_converter.get_all_value_added_services([OCPICapabilityEnum.RESERVABLE])
        [<ValueAddedService.Reservation: 'Reservation'>]

        This function collects all of the matching ValueAddedServices for the given list of OCPI 2.2.1 Capabilities.
        @param capabilities: List of OCPI 2.2.1 Capabilities
        @return: List of corresponding ValueAddedService enums
        """

        # todo : Item AuthenticationModes cannot map other modes directly to OICP
        return [
            vas
            for vas in (
                self.map_capability_to_value_added_services(capability)
                for capability in capabilities
            )
            if vas
        ]

    def map_ocpi_parking_types_to_accessibility_locations(
        self,
        parking_type: str,
    ) -> AccessibilityLocation:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.map_ocpi_parking_types_to_accessibility_locations('PARKING_GARAGE')
        <AccessibilityLocation.ParkingGarage: 'ParkingGarage'>
        >>> oicp_converter.map_ocpi_parking_types_to_accessibility_locations('PARKING_LOT')
        <AccessibilityLocation.ParkingLot: 'ParkingLot'>
        >>> oicp_converter.map_ocpi_parking_types_to_accessibility_locations('UNKNOWN')

        """

        return {
            "PARKING_GARAGE": AccessibilityLocation.ParkingGarage,
            "PARKING_LOT": AccessibilityLocation.ParkingLot,
            "ON_STREET": AccessibilityLocation.OnStreet,
            "UNDERGROUND_GARAGE": AccessibilityLocation.UndergroundParkingGarage,
        }.get(parking_type, None)

    def get_timezone(self, timezone: str):
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.get_timezone('Europe/Helsinki')
        'UTC+03:00'
        >>> oicp_converter.get_timezone('Asia/Colombo')
        'UTC+05:30'
        >>> oicp_converter.get_timezone('Asia/Kathmandu')
        'UTC+05:45'
        >>> oicp_converter.get_timezone('Unknown')
        Traceback (most recent call last):
              ...
        django.core.exceptions.ValidationError: ['Unknown timezone: Unknown']
        """
        try:
            tz = datetime.now(pytz.timezone(timezone))
            return tz.strftime("UTC%z")[:6] + ":" + tz.strftime("UTC%z")[6:]
        except pytz.exceptions.UnknownTimeZoneError:
            raise ValidationError(f"Unknown timezone: {timezone}")

    def get_payment_options(
        self,
        capabilities: List[OCPICapabilityEnum],
    ) -> list[PaymentOption]:
        """
        >>> oicp_converter = OCPIToOICPConverter('2.2.1', '2.2')
        >>> oicp_converter.get_payment_options([OCPICapabilityEnum.CHIP_CARD_SUPPORT, OCPICapabilityEnum.CONTACTLESS_CARD_SUPPORT, OCPICapabilityEnum.CREDIT_CARD_PAYABLE])
        [<PaymentOption.Direct: 'Direct'>]
        >>> oicp_converter.get_payment_options([OCPICapabilityEnum.RFID_READER])
        [<PaymentOption.Contract: 'Contract'>]
        >>> oicp_converter.get_payment_options([OCPICapabilityEnum.PED_TERMINAL, OCPICapabilityEnum.RESERVABLE])
        []
        """

        capability_map = {
            PaymentOption.Direct: [
                OCPICapabilityEnum.CHIP_CARD_SUPPORT,
                OCPICapabilityEnum.CONTACTLESS_CARD_SUPPORT,
                OCPICapabilityEnum.CREDIT_CARD_PAYABLE,
                OCPICapabilityEnum.DEBIT_CARD_PAYABLE,
            ],
            PaymentOption.Contract: [
                OCPICapabilityEnum.RFID_READER,
            ],
        }

        # Build the payment options list based on capabilities
        payment_options = [
            option
            for option, required_capabilities in capability_map.items()
            if any(capability in capabilities for capability in required_capabilities)
        ]

        # TODO: No Payment will be determined separately with tariffs
        return payment_options
