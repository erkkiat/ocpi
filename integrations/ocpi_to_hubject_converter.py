import functools
import re
from datetime import datetime
from typing import Optional

import pytz
from django.conf import settings
from django.core.exceptions import ValidationError

from integrations.hubject.schemas import (
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


class OCPIToHubjectConverter:
    def __init__(self, oicp_version: str = None, ocpi_version: str = None):
        self.oicp_version = oicp_version
        self.ocpi_version = ocpi_version
        self.address_pattern = re.compile(r"(?P<street>[^\d]+)\s(?P<house>\d+)")

        self.general_address_pattern = re.compile(
            r"(?P<street>[A-Za-z\s.-]+?)\s+(?P<house>\d+[A-Za-z]?(?:-\d+)?)"
        )
        self.france_pattern = re.compile(
            r"(?P<house>\d+[A-Za-z]?)\s+(?P<street>(?:Rue|Avenue|Boulevard|Chemin)\s+[A-Za-z\s.-]+)",
            re.IGNORECASE,
        )

    def convert_to_operator_evse_data(self, location: Location) -> OperatorEvseData:
        return OperatorEvseData(
            OperatorID=location.party_str(),
            OperatorName=location.owner.name if location.owner else "",
            EvseDataRecord=[
                self._convert_to_evse_data_record(evse, location)
                for evse in location.evses.all()
            ],
        )

    def _convert_to_evse_data_record(
        self, evse: Evse, location: Location
    ) -> EvseDataRecord:
        street, house_number = self.get_address_components(
            location.address, location.country
        )
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
                Street=street,
                PostalCode=location.postal_code,
                HouseNum=house_number,
                # todo : Floor missing in ocpi22,
                # todo : Region missing in ocpi22,
                ParkingFacility=True if location.parking_type else False,
                # todo : ParkingSpot missing in ocpi22,
                TimeZone=self.get_timezone(location.time_zone),
            ),
            GeoCoordinates=GeoCoordinates(
                Google=None,
                DecimalDegree=DecimalDegree(
                    Latitude="{:.6f}".format(location.latitude),
                    Longitude="{:.6f}".format(location.longitude),
                ),
                DegreeMinuteSeconds=None,
            ),
            Plugs=self.get_distinct_plugs(evse.connectors.all()),
            DynamicPowerLevel=None,
            ChargingFacilities=self.get_charging_facilities(evse.connectors.all()),
            # todo : RenewableEnergy check with smappee, default to False
            RenewableEnergy=False,
            # todo : EnergySource missing in ocpi22 location model, But it can be found in OCPIEnergyMix, is not clearly mapping directly to OICP
            EnergySource=None,
            # todo : EnvironmentalImpact missing in ocpi22, But it can be found in OCPIEnergyMix, is not clearly mapping directly to OICP
            EnvironmentalImpact=None,
            # todo : CalibrationLawDataAvailability missing in ocpi22, required, defaulted to Local
            CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
            AuthenticationModes=self.get_authentication_modes_list(evse.capabilities),
            # todo : MaxCapacity missing in ocpi22,
            MaxCapacity=None,
            # todo : PaymentOptions missing in ocpi22,
            PaymentOptions=self.get_payment_options(evse.capabilities),
            ValueAddedServices=self.get_value_added_services_list(evse.capabilities),
            # todo : Accessibility missing in ocpi22, default to free, discuss with smappee
            Accessibility=Accessibility.Free_publicly_accessible,
            AccessibilityLocation=self.get_accessibility_locations(
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
                    Latitude="{:.6f}".format(location.latitude),
                    Longitude="{:.6f}".format(location.longitude),
                ),
                DegreeMinuteSeconds=None,
            ),
            # todo : IsOpen24Hours usage of the charging when closed does not directly map to OCIP,
            IsOpen24Hours=location.charging_when_closed,
            # todo : OpeningTimes missing in ocpi22,
            OpeningTimes=None,
            # todo : HubOperatorID missing in ocpi22,
            # todo : ClearinghouseID missing in ocpi22,
            IsHubjectCompatible=False,
            DynamicInfoAvailable=DynamicInfoAvailable.false,
        )

    def get_plug(self, connector_std: str) -> Plug:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_plug('IEC_62196_T2')
        <Plug.Type_2_Outlet: 'Type 2 Outlet'>
        >>> oicp_converter.get_plug('CHADEMO')
        <Plug.CHAdeMO: 'CHAdeMO'>
        >>> oicp_converter.get_plug('TESLA_S')
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
        }
        plug = mapping.get(connector_std.upper())
        if not plug:
            raise ValidationError(f"'{connector_std}' is not a known connector type.")
        return plug

    def get_distinct_plugs(self, connectors: list[Connector]) -> set[Plug]:
        """
        This function collects only the distinct plugs from the given list of OCPI 2.2.1 Connectors.
        @param connectors: List of OCPI 2.2.1 Connectors
        @return: Set of corresponding Plug enums
        """
        return {self.get_plug(connector.standard) for connector in connectors}

    def get_power_type(self, power_type_choice_221: str) -> PowerType:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_power_type('AC_1_PHASE')
        <PowerType.AC_1_PHASE: 'AC_1_PHASE'>
        >>> oicp_converter.get_power_type('DC')
        <PowerType.DC: 'DC'>

        @param power_type_choice_221: OCPI 2.2.1 PowerType Choice
        @return: Corresponding Plug enum for the given power type choice
        """
        mapping = {
            "AC_1_PHASE": PowerType.AC_1_PHASE,
            "AC_3_PHASE": PowerType.AC_3_PHASE,
            "DC": PowerType.DC,
        }

        power_type = mapping.get(power_type_choice_221.upper())

        if not power_type:
            raise ValidationError(
                f"'{power_type_choice_221}' is not a known POWERTYPE_221."
            )

        return power_type

    def get_charging_facilities(
        self, connectors: list[Connector]
    ) -> list[ChargingFacility]:
        return [
            ChargingFacility(
                PowerType=self.get_power_type(connector.power_type),
                Voltage=connector.max_voltage,
                Amperage=connector.max_amperage,
                Power=connector.power_kw(),
            )
            for connector in connectors
        ]

    @functools.cache
    def get_address_extractor(self, country: str):
        """
        Returns a function to extract both house number and street based on the country/address format.
        """

        def extract_general_address(addr):
            match = self.general_address_pattern.search(addr)
            if match:
                return match.group("house"), match.group("street").strip()
            return "-", "-"

        def extract_french_address(addr):
            match = self.france_pattern.search(addr)
            if match:
                return match.group("house"), match.group("street").strip()
            return "-", "-"

        return dict(FRA=extract_french_address).get(country, extract_general_address)

    def get_address_components(self, address: str, country: str) -> (str, str):
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_address_components("Weteringstraat 34-1", 'NLD')
        ('Weteringstraat', '34-1')
        >>> oicp_converter.get_address_components("23 Rue de Grenelle", 'FRA')
        ('Rue de Grenelle', '23')
        >>> oicp_converter.get_address_components("Weberstr. 2", 'DEU')
        ('Weberstr.', '2')
        >>> oicp_converter.get_address_components("Kandintie 4E", 'FIN')
        ('Kandintie', '4E')
        """
        extractor = self.get_address_extractor(country)
        house_number, street = extractor(address)
        return street, house_number

    def get_authentication_mode(
        self,
        capability: OCPICapabilityEnum,
    ) -> Optional[AuthenticationMode]:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_authentication_mode(OCPICapabilityEnum.RFID_READER)
        <AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>
        """

        mapping = {
            OCPICapabilityEnum.RFID_READER: AuthenticationMode.NFC_RFID_Classic,
        }
        return mapping.get(capability)

    def get_authentication_modes_list(
        self,
        capabilities: list[OCPICapabilityEnum],
    ) -> list[AuthenticationMode]:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_authentication_modes_list([OCPICapabilityEnum.RFID_READER])
        [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
        >>> oicp_converter.get_authentication_modes_list([OCPICapabilityEnum.RFID_READER, OCPICapabilityEnum.CREDIT_CARD_PAYABLE])
        [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
        >>> oicp_converter.get_authentication_modes_list([OCPICapabilityEnum.UNLOCK_CAPABLE])
        []

        This function collects all of the matching AuthenticationModes for the given list of OCPI 2.2.1 Capabilities.
        @param capabilities: List of OCPI 2.2.1 Capabilities
        @return: List of corresponding AuthenticationMode enums
        """

        # todo : Item AuthenticationModes cannot map all modes directly to OICP
        return [
            mode
            for capability in (capabilities or [])
            for mode in [self.get_authentication_mode(capability)]
            if mode is not None
        ]

    def get_value_added_services(
        self,
        capability: OCPICapabilityEnum,
    ) -> Optional[ValueAddedService]:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_value_added_services(OCPICapabilityEnum.RESERVABLE)
        <ValueAddedService.Reservation: 'Reservation'>
        """

        mapping = {
            OCPICapabilityEnum.RESERVABLE: ValueAddedService.Reservation,
        }
        return mapping.get(capability)

    def get_value_added_services_list(
        self,
        capabilities: list[OCPICapabilityEnum],
    ) -> list[ValueAddedService]:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_value_added_services_list([OCPICapabilityEnum.CHARGING_PROFILE_CAPABLE])
        []
        >>> oicp_converter.get_value_added_services_list([OCPICapabilityEnum.RESERVABLE])
        [<ValueAddedService.Reservation: 'Reservation'>]

        This function collects all of the matching ValueAddedServices for the given list of OCPI 2.2.1 Capabilities.
        @param capabilities: List of OCPI 2.2.1 Capabilities
        @return: List of corresponding ValueAddedService enums
        """

        return [
            vas
            for capability in (capabilities or [])
            for vas in [self.get_value_added_services(capability)]
            if vas is not None
        ]

    def get_accessibility_locations(
        self,
        parking_type: str,
    ) -> Optional[AccessibilityLocation]:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
        >>> oicp_converter.get_accessibility_locations('PARKING_GARAGE')
        <AccessibilityLocation.ParkingGarage: 'ParkingGarage'>
        >>> oicp_converter.get_accessibility_locations('PARKING_LOT')
        <AccessibilityLocation.ParkingLot: 'ParkingLot'>
        >>> oicp_converter.get_accessibility_locations('UNKNOWN')

        """

        mapping = {
            "PARKING_GARAGE": AccessibilityLocation.ParkingGarage,
            "PARKING_LOT": AccessibilityLocation.ParkingLot,
            "ON_STREET": AccessibilityLocation.OnStreet,
            "UNDERGROUND_GARAGE": AccessibilityLocation.UndergroundParkingGarage,
        }
        return mapping.get(parking_type)

    def get_timezone(self, timezone: str):
        """
        >>> oicp_converter = OCPIToHubjectConverter()
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
            return f"{tz.strftime('UTC%z')[:6]}:{tz.strftime('UTC%z')[6:]}"
        except pytz.exceptions.UnknownTimeZoneError:
            raise ValidationError(f"Unknown timezone: {timezone}")

    def get_payment_options(
        self,
        capabilities: list[OCPICapabilityEnum],
    ) -> list[PaymentOption]:
        """
        >>> oicp_converter = OCPIToHubjectConverter()
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
            if capabilities
            and any(capability in capabilities for capability in required_capabilities)
        ]

        # TODO: No Payment will be determined separately with tariffs
        return payment_options
