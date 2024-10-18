import uuid
from collections import defaultdict
from itertools import chain
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
    GeoCoordinates,
)
from ocpi22.choices import OCPICapabilityEnum
from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.location import Location, Evse, Connector
from datetime import datetime

from ocpi22.util import calculate_partition

import pytz
import hashlib

from ocpiconnector.ocpi_identities import Party


class HubjectToOCPIConverter:
    def __init__(self, oicp_version: str = None, ocpi_version: str = None):
        self.oicp_version = oicp_version
        self.ocpi_version = ocpi_version
        self.locations = []
        self.ocpi_evses = []
        self.connectors = []

    payment_options_ocpi_capability_map = {
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

    value_added_service_capability_map = {
        ValueAddedService.Reservation: OCPICapabilityEnum.RESERVABLE,
    }

    auth_mode_capability_map = {
        AuthenticationMode.NFC_RFID_Classic: OCPICapabilityEnum.RFID_READER,
    }

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
            capabilities=set(
                self.get_capabilities(
                    evse.AuthenticationModes,
                    evse.ValueAddedServices,
                    evse.PaymentOptions,
                )
            ),
            location=location,
        )

    def convert_to_locations(
        self, evse_data_record: EvseDataRecord, owner: Party
    ) -> Location:
        coords = self.get_geo_coordinates(evse_data_record.GeoCoordinates)
        existing_location = Location.objects.get(
            name=evse_data_record.ChargingStationNames[0].value
        )
        return Location(
            # todo: Add an identifier for hubject
            # ocpi_master=,
            uid=existing_location.uid if existing_location else uuid.uuid4(),
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
            latitude=coords[0],
            longitude=coords[1],
            lat_partition=calculate_partition(coords[0]),
            long_partition=calculate_partition(coords[1]),
            # todo OICP has a boolean for parking_type
            # parking_type=
            last_updated=evse_data_record.lastUpdate,
            # todo : OICP cannot be directly converted to facilities
            # facilities=
            charging_when_closed=evse_data_record.IsOpen24Hours,
            # todo: Ask from hubject about operator, suboperator
            # operator=,
            # suboperator=,
            owner=BusinessDetails(
                name=owner.__str__(),
            ),
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
                    f"{now.strftime('UTC%z')[:6]}:{now.strftime('UTC%z')[6:]}"
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
        vas_list: List[ValueAddedService],
        payment_options: List[PaymentOption],
    ) -> chain[OCPICapabilityEnum | None]:
        auth_mode_map = HubjectToOCPIConverter.auth_mode_capability_map
        vas_map = HubjectToOCPIConverter.value_added_service_capability_map
        payment_options_map = HubjectToOCPIConverter.payment_options_ocpi_capability_map

        return chain(
            (auth_mode_map.get(auth_mode) for auth_mode in authentication_modes),
            [vas_map.get(vas) for vas in vas_list],
            [
                item
                for payment_option in payment_options
                for item in payment_options_map.get(payment_option, [])
            ],
        )

    def get_geo_coordinates(self, coordinates: GeoCoordinates) -> list:
        def get_coordinates_from_google_format():
            return coordinates.Google.Coordinates.split(" ")

        def get_coordinates_from_decimal_degree_format():
            return [
                coordinates.DecimalDegree.Latitude,
                coordinates.DecimalDegree.Longitude,
            ]

        def get_coordinates_from_decimal_degree_minutes_format():
            # todo will be completed in ST-101
            return []

        if coordinates.Google is not None:
            return get_coordinates_from_google_format()
        elif coordinates.DecimalDegree is not None:
            return get_coordinates_from_decimal_degree_format()
        elif coordinates.DegreeMinuteSeconds is not None:
            return get_coordinates_from_decimal_degree_minutes_format()
