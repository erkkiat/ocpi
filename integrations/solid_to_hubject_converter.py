import functools
import regex
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import pytz
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Max

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
    HubjectDefaultTariff,
    PricingProductData,
    CurrencyID,
    ReferenceUnit,
    ProviderIDAsterisk,
    PricingProductDataRecord,
    HubjectPriceComponent,
    AdditionalReference,
    AdditionalReferenceChoice,
    ERoamingChargeDetailRecord,
    OperatorID,
    ProviderID,
    Identification,
    UID,
    ProductID,
    RFIDMifareFamilyIdentificationClass,
    EvseStatus as OICPEvseStatus,
)
from ocpi22.choices import OCPICapability
from ocpi22.cpo.repositories import SolidTariffRepository
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.tariff import SolidTariff

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ocpi22.models.cdr import Cdr


class SolidToHubjectConverter:
    def __init__(self, oicp_version: str = None, ocpi_version: str = None):
        self.oicp_version = oicp_version
        self.ocpi_version = ocpi_version
        self.address_pattern = regex.compile(r"(?P<street>[^\d]+)\s(?P<house>\d+)")

        self.general_address_pattern = regex.compile(
            r"^\s*(?P<street>\p{L}[\p{L}\d\s.'’\-]*?)\s*(?:,\s*|\s+)\s*(?P<house>\d+\w*(?:-\d+)?)\b",
            regex.IGNORECASE,
        )
        self.france_pattern = regex.compile(
            r"^\s*(?P<house>\d{1,4})[\s,]+(?P<street>[A-Za-zÀ-ÖØ-öø-ÿ\s.'’\-]+)$",
            regex.IGNORECASE,
        )

    def convert_to_operator_evse_data(self, location: Location) -> OperatorEvseData:
        return OperatorEvseData(
            OperatorID=location.party_str(),
            OperatorName=self.get_operator_name(location),
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
            EvseID=self.get_evse_id(evse.evse_id),
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
            ChargingStationNames=[
                InfoTextType(lang="en", value=location.name if location.name else "")
            ],
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
            # todo : OpeningTimes will be implemented later,
            OpeningTimes=None,
            # todo : HubOperatorID missing in ocpi22,
            # todo : ClearinghouseID missing in ocpi22,
            IsHubjectCompatible=False,
            DynamicInfoAvailable=DynamicInfoAvailable.false,
        )

    def get_evse_id(self, evse_id: str) -> EvseID:
        """
        >>> oicp_converter = SolidToHubjectConverter()
        >>> oicp_converter.get_evse_id("FI*SMP*34567")
        EvseID(root='FI*SMP*E34567')
        """
        hubject_evse_id = regex.sub(r"^([A-Z]{2}\*[A-Z]+\*)(?!E)", r"\1E", evse_id)
        return EvseID(hubject_evse_id)

    def get_operator_name(self, location: Location) -> str:
        # TODO This is risky, need to think where to put this, option 1 - having it as a env variable
        return (
            location.ocpi_master.business_details.name
            if location.ocpi_master.business_details
            else location.owner.name
            if location.owner
            else ""
        )

    def convert_to_pricing_product_data(
        self,
        solid_tariffs: list[SolidTariff],
        hubject_default_tariff: HubjectDefaultTariff,
        operator_id: str,
        operator_name: str,
    ) -> PricingProductData:
        return PricingProductData(
            OperatorID=operator_id,
            OperatorName=operator_name,
            PricingDefaultPrice=hubject_default_tariff.price,
            PricingDefaultPriceCurrency=CurrencyID(
                root=hubject_default_tariff.currency
            ),
            PricingDefaultReferenceUnit=ReferenceUnit(
                root=hubject_default_tariff.price_component
            ),
            PricingProductDataRecords=[
                record
                for solid_tariff in solid_tariffs
                for record in self.convert_to_pricing_product_data_records(
                    solid_tariff, operator_id
                )
            ],
            # todo: Offer to all should not be used in production.
            ProviderID=self.get_provider_ids(solid_tariffs),
        )

    def get_provider_ids(self, solid_tariffs: list[SolidTariff]) -> ProviderIDAsterisk:
        # Todo: when we have multiple providers we need to send a list
        if solid_tariffs[0].msp is None:
            return ProviderIDAsterisk(root="*")
        return ProviderIDAsterisk(root=solid_tariffs[0].msp.party_str())

    def convert_to_pricing_product_data_records(
        self,
        solid_tariff: SolidTariff,
        operator_id: str,
    ) -> list[PricingProductDataRecord]:
        conditions = [
            (
                HubjectPriceComponent.KWH,
                solid_tariff.price_per_kwh,
            ),
            (
                HubjectPriceComponent.MINUTE,
                solid_tariff.price_per_min,
            ),
        ]

        pricing_product_data_records = []
        for ref_unit, price in conditions:
            if price is not None:
                pricing_product_data_records.append(
                    PricingProductDataRecord(
                        AdditionalReferences=[
                            AdditionalReference(
                                AdditionalReference=AdditionalReferenceChoice.START_FEE,
                                AdditionalReferenceUnit=ReferenceUnit(
                                    root=HubjectPriceComponent.HOUR.value
                                ),
                                PricePerAdditionalReferenceUnit=solid_tariff.price_flat,
                            ),
                        ],
                        IsValid24hours=True,
                        MaximumProductChargingPower=self.get_maximum_product_charging_power(),
                        PricePerReferenceUnit=price,
                        ProductAvailabilityTimes=[],
                        ProductID=self.get_pricing_product_id(
                            solid_tariff.external_id,
                            ref_unit,
                            operator_id,
                            solid_tariff.msp.party_str() if solid_tariff.msp else "",
                        ),
                        ProductPriceCurrency=solid_tariff.currency,
                        ReferenceUnit=ReferenceUnit(root=ref_unit),
                    )
                )
        return pricing_product_data_records

    def get_maximum_product_charging_power(self):
        return (
            Connector.objects.aggregate(Max("max_electric_power"))[
                "max_electric_power__max"
            ]
            or 0
        ) / 1000

    def get_pricing_product_id(
        self,
        solid_tariff_id: str,
        ref_unit: HubjectPriceComponent,
        operator_id: str,
        msp_id: str,
    ) -> str:
        if not operator_id or not solid_tariff_id or not ref_unit:
            raise ValueError(
                "Missing required fields {operator_id, price_reference, solid_tariff_external_id} for generating pricing product ID."
            )
        return f"{operator_id}*{solid_tariff_id}*{ref_unit.value}*{msp_id}"

    def get_plug(self, connector_std: str) -> Plug:
        """
        >>> oicp_converter = SolidToHubjectConverter()
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
        >>> oicp_converter = SolidToHubjectConverter()
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
            "AC": PowerType.AC_3_PHASE,
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
                Voltage=max(0, connector.max_voltage),
                Amperage=max(0, connector.max_amperage),
                Power=max(0, connector.power_kw()),
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
            return extract_general_address(addr)

        if country == "FRA":
            return extract_french_address
        return extract_general_address

    def get_address_components(self, address: str, country: str) -> (str, str):
        """
        >>> oicp_converter = SolidToHubjectConverter()
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
        capability: OCPICapability,
    ) -> Optional[AuthenticationMode]:
        """
        >>> oicp_converter = SolidToHubjectConverter()
        >>> oicp_converter.get_authentication_mode(OCPICapability.RFID_READER)
        <AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>
        """

        mapping = {
            OCPICapability.RFID_READER: AuthenticationMode.NFC_RFID_Classic,
        }
        return mapping.get(capability)

    def get_authentication_modes_list(
        self,
        capabilities: list[OCPICapability],
    ) -> list[AuthenticationMode]:
        """
        >>> oicp_converter = SolidToHubjectConverter()
        >>> oicp_converter.get_authentication_modes_list([OCPICapability.RFID_READER])
        [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
        >>> oicp_converter.get_authentication_modes_list([OCPICapability.RFID_READER, OCPICapability.CREDIT_CARD_PAYABLE])
        [<AuthenticationMode.NFC_RFID_Classic: 'NFC RFID Classic'>]
        >>> oicp_converter.get_authentication_modes_list([OCPICapability.UNLOCK_CAPABLE])
        [<AuthenticationMode.No_Authentication_Required: 'No Authentication Required'>]

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
        ] or [AuthenticationMode.No_Authentication_Required]

    def get_value_added_services(
        self,
        capability: OCPICapability,
    ) -> Optional[ValueAddedService]:
        """
        >>> oicp_converter = SolidToHubjectConverter()
        >>> oicp_converter.get_value_added_services(OCPICapability.RESERVABLE)
        <ValueAddedService.Reservation: 'Reservation'>
        """

        mapping = {
            OCPICapability.RESERVABLE: ValueAddedService.Reservation,
        }
        return mapping.get(capability)

    def get_value_added_services_list(
        self,
        capabilities: list[OCPICapability],
    ) -> list[ValueAddedService]:
        """
        >>> oicp_converter = SolidToHubjectConverter()
        >>> oicp_converter.get_value_added_services_list([OCPICapability.CHARGING_PROFILE_CAPABLE])
        [<ValueAddedService.None_: 'None'>]
        >>> oicp_converter.get_value_added_services_list([OCPICapability.RESERVABLE])
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
        ] or [ValueAddedService.None_]

    def get_accessibility_locations(
        self,
        parking_type: str,
    ) -> Optional[AccessibilityLocation]:
        """
        >>> oicp_converter = SolidToHubjectConverter()
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
        >>> oicp_converter = SolidToHubjectConverter()
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
        capabilities: list[OCPICapability],
    ) -> list[PaymentOption]:
        """
        >>> oicp_converter = SolidToHubjectConverter()
        >>> oicp_converter.get_payment_options([OCPICapability.CHIP_CARD_SUPPORT, OCPICapability.CONTACTLESS_CARD_SUPPORT, OCPICapability.CREDIT_CARD_PAYABLE])
        [<PaymentOption.Direct: 'Direct'>]
        >>> oicp_converter.get_payment_options([OCPICapability.RFID_READER])
        [<PaymentOption.Contract: 'Contract'>]
        >>> oicp_converter.get_payment_options([OCPICapability.PED_TERMINAL, OCPICapability.RESERVABLE])
        [<PaymentOption.Contract: 'Contract'>]
        """

        capability_map = {
            PaymentOption.Direct: [
                OCPICapability.CHIP_CARD_SUPPORT,
                OCPICapability.CONTACTLESS_CARD_SUPPORT,
                OCPICapability.CREDIT_CARD_PAYABLE,
                OCPICapability.DEBIT_CARD_PAYABLE,
            ],
            PaymentOption.Contract: [
                OCPICapability.RFID_READER,
            ],
        }

        # Build the payment options list based on capabilities
        payment_options = [
            option
            for option, required_capabilities in capability_map.items()
            if capabilities
            and any(capability in capabilities for capability in required_capabilities)
        ] or [PaymentOption.Contract]

        # TODO: No Payment will be determined separately with tariffs
        return payment_options

    def convert_cdr_to_eroaming_charging_detail_record(
        self, cdr: "Cdr"
    ) -> ERoamingChargeDetailRecord:
        from ocpi22.cpo.api import applying_tariff_element
        from ocpi22.models.session import Session

        session = Session.objects.filter(uid__iexact=cdr.session_id).first()
        if not session:
            raise ValidationError(f"No session found for ID {cdr.session_id}")

        msp_party_str = cdr.billed_to.party_str()
        operator_party_str = cdr.ocpi_master.party_str()

        current_tariff_element = applying_tariff_element(session)
        solid_tariff = SolidTariffRepository.find_by_ocpi_tariff_id(
            current_tariff_element.tariff.uid
        )
        partner_product_id = None
        if solid_tariff:
            partner_product_id = self.get_pricing_product_id(
                solid_tariff.external_id,
                HubjectPriceComponent.KWH,
                operator_party_str,
                msp_party_str,
            )

        eroaming_cdr = ERoamingChargeDetailRecord(
            session_id=session.hub_session_id,
            cpo_partner_session_id=session.uid,
            emp_partner_session_id=session.reservation_id,
            partner_product_id=(
                ProductID(root=partner_product_id) if partner_product_id else None
            ),
            evse_id=EvseID(root=cdr.evse_id),
            identification=Identification(
                RFIDMifareFamilyIdentification=RFIDMifareFamilyIdentificationClass(
                    UID=UID(root=session.token_id)
                ),
            ),
            charging_start=cdr.start_date_time,
            charging_end=cdr.end_date_time,
            session_start=cdr.start_date_time,
            session_end=cdr.end_date_time,
            meter_value_start=session.start_kwh,
            meter_value_end=session.stop_kwh,
            meter_value_in_between=None,
            consumed_energy=cdr.total_energy,
            signed_metering_values=None,
            calibration_law_verification_info=None,
            hub_operator_id=OperatorID(root=operator_party_str),
            hub_provider_id=ProviderID(root=msp_party_str),
        )

        evse_data_record = self._convert_to_evse_data_record(
            session.evse, session.location
        )

        if (
            evse_data_record.CalibrationLawDataAvailability
            == CalibrationLawDataAvailability.External
        ):
            if eroaming_cdr.signed_metering_values is None:
                logger.error(
                    "SignedMeteringValues must be provided when CalibrationLawDataAvailability is External in ERoamingChargeDetailRecord."
                )
                raise ValidationError(
                    "SignedMeteringValues must be provided when CalibrationLawDataAvailability is External."
                )

        return eroaming_cdr

    def convert_ocpi_evse_status(self, status: str) -> OICPEvseStatus:
        match status.upper():
            case "AVAILABLE":
                return OICPEvseStatus.Available
            case "BLOCKED":
                return OICPEvseStatus.Occupied
            case "CHARGING":
                return OICPEvseStatus.Occupied
            case "INOPERATIVE":
                return OICPEvseStatus.OutOfService
            case "OUTOFORDER":
                return OICPEvseStatus.OutOfService
            case "PLANNED":
                return OICPEvseStatus.Occupied
            case "REMOVED":
                return OICPEvseStatus.OutOfService
            case "RESERVED":
                return OICPEvseStatus.Reserved
            case "UNKNOWN":
                return OICPEvseStatus.Unknown
            case _:
                raise ValueError(f"Invalid OCPI status [{status}] found")
