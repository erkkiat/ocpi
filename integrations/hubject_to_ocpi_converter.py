import uuid
from collections import defaultdict
from typing import List

from django.core.exceptions import ValidationError

from integrations.hubject.schemas import (
    ERoamingPushEvseData,
    Address,
    AuthenticationMode,
    ValueAddedService,
    PaymentOption,
    EvseDataRecord,
    OperatorID,
)
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.location import Location, Evse, Connector
from datetime import datetime

from ocpi22.util import calculate_partition

import pytz
import hashlib


class HubjectToOCPIConverter:
    def __init__(self, oicp_version: str, ocpi_version: str):
        self.oicp_version = oicp_version
        self.ocpi_version = ocpi_version
        self.locations = []
        self.ocpi_evses = []
        self.connectors = []

    def __convert_to_connectors(
        self, hubject_evse: EvseDataRecord, ocpi_evse: Evse
    ) -> List[Connector]:
        hubject_connectors = hubject_evse.ChargingFacilities
        ocpi_connectors = []
        for c in hubject_connectors:
            new_connector = Connector(
                uid=uuid.uuid4(),
                evse=ocpi_evse,
                # todo - standard cannot be directly converted from hubject
                # standard=,
                # todo - format cannot be directly converted from hubject
                # format=,
                # tariff_ids=,
                power_type=c.PowerType.value,
                max_voltage=c.Voltage,
                max_amperage=c.Amperage,
                max_electric_power=c.Power,
                # todo - terms_and_conditions cannot be directly converted from hubject
                # terms_and_conditions="",
                last_updated=hubject_evse.lastUpdate,
            )
            ocpi_connectors.append(new_connector)

        return ocpi_connectors

    def __convert_to_evse(self, evse: EvseDataRecord, location: Location) -> Evse:
        return Evse(
            evse_id=evse.EvseID.root,
            # todo status cannot be directly convert from hubject
            # status=
            last_updated=evse.lastUpdate,
            capabilities=self.get_capabilities(
                evse.AuthenticationModes, evse.ValueAddedServices, evse.PaymentOptions
            ),
            location=location,
        )

    def convert_to_locations(
        self, evse_data_record: EvseDataRecord, owner: str
    ) -> Location:
        return Location(
            # todo: Add an identifier for hubject
            # ocpi_master=,
            uid=uuid.uuid4(),
            # todo: OICP cannot be converted to publish field directly
            # publish=,
            name=evse_data_record.ChargingStationNames[0].value
            if evse_data_record.ChargingStationNames
            else "",
            address=self.get_address(evse_data_record.Address),
            city=evse_data_record.Address.City,
            postal_code=evse_data_record.Address.PostalCode,
            state=evse_data_record.Address.Region,
            country=evse_data_record.Address.Country,
            time_zone=self.get_timezone(evse_data_record.Address.TimeZone),
            latitude=evse_data_record.GeoCoordinates.DecimalDegree.Latitude,
            longitude=evse_data_record.GeoCoordinates.DecimalDegree.Longitude,
            lat_partition=calculate_partition(
                evse_data_record.GeoCoordinates.DecimalDegree.Latitude
            ),
            long_partition=calculate_partition(
                evse_data_record.GeoCoordinates.DecimalDegree.Longitude
            ),
            # todo OICP has a boolean for parking_type
            # parking_type=
            last_updated=datetime.now(pytz.utc),
            # todo : OICP cannot be directly converted to facilities
            # facilities=
            charging_when_closed=evse_data_record.IsOpen24Hours,
            # todo: Ask from hubject about operator, suboperator
            # operator=,
            # suboperator=,
            owner=owner,
        )

    def convert(self, eroaming_data: ERoamingPushEvseData):
        operator_evse_data = eroaming_data.OperatorEvseData
        locations_evse_map = self.get_location_evse_map(
            operator_evse_data.EvseDataRecord
        )
        owner, _ = BusinessDetails.objects.get_or_create(
            name=operator_evse_data.OperatorName
        )
        for location_hash_key in locations_evse_map.keys():
            # If the evses are in the same location, data related to the location will be the same
            evse_data_record = locations_evse_map[location_hash_key][0]
            location = self.convert_to_locations(evse_data_record, owner)
            self.locations.append(location)

            for evse_data_record in locations_evse_map[location_hash_key]:
                tmp_evse = self.__convert_to_evse(evse_data_record, location)
                tmp_connectors = self.__convert_to_connectors(
                    evse_data_record, tmp_evse
                )
                self.ocpi_evses.append(tmp_evse)
                self.connectors.extend(tmp_connectors)

    def get_location_evse_map(self, evses: List[EvseDataRecord]) -> dict:
        location_map = defaultdict(list)
        for evse in evses:
            address_hash = hashlib.sha256(
                f"{evse.Address.Street}{evse.Address.HouseNum}{evse.Address.PostalCode}{evse.Address.City}{evse.Address.Country}".encode(
                    "utf-8"
                )
            ).hexdigest()
            location_map[address_hash].append(evse)
        return location_map

    def get_timezone(self, utc_offset: str):
        """
        >>> oicp_to_ocpi = HubjectToOCPIConverter()
        >>> oicp_to_ocpi.get_timezone('UTC+03:00')
        'Europe/Helsinki'
        >>> oicp_to_ocpi.get_timezone('UTC+05:30')
        'Asia/Colombo'
        >>> oicp_to_ocpi.get_timezone('UTC+05:45')
        'Asia/Kathmandu'
        >>> oicp_to_ocpi.get_timezone('UTC+00:00')
        'UTC'
        >>> oicp_to_ocpi.get_timezone('UTC+99:99')
        Traceback (most recent call last):
            ...
        django.core.exceptions.ValidationError: ['Unknown UTC offset: UTC+99:99']
        """
        for tz in pytz.all_timezones:
            try:
                now = datetime.now(pytz.timezone(tz))
                if (
                    now.strftime("UTC%z")[:6] + ":" + now.strftime("UTC%z")[6:]
                    == utc_offset
                ):
                    return tz
            except pytz.exceptions.UnknownTimeZoneError:
                raise ValidationError(f"Unknown UTC offset: {utc_offset}")

    def get_address(self, address: Address) -> str:
        return f"{address.Street}, {address.HouseNum}"

    def get_operator(self, operator: OperatorID): ...

    def get_capabilities(
        self,
        authentication_modes: List[AuthenticationMode],
        vas: List[ValueAddedService],
        payment_options: List[PaymentOption],
    ) -> List[str]:
        auth_mode_map = self.get_authentication_mode_map()
        vas_map = self.get_value_added_services_map()
        payment_options_map = self.get_payment_options_map()

        capabilities = set()

        for auth_mode in authentication_modes:
            capabilities.add(auth_mode_map.get(auth_mode))

        for vas in vas:
            capabilities.add(vas_map.get(vas))

        for payment_option in payment_options:
            capabilities.update(payment_options_map.get(payment_option))

        return list(capabilities)

    def get_authentication_mode_map(self) -> dict:
        return {
            AuthenticationMode.NFC_RFID_Classic: OCPICapabilityEnum.RFID_READER,
        }

    def get_value_added_services_map(self) -> dict:
        return {
            ValueAddedService.Reservation: OCPICapabilityEnum.RESERVABLE,
        }

    def get_payment_options_map(self) -> dict:
        return {
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
