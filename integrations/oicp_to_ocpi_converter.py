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
from ocpi22.models.location import Location, Evse
from datetime import datetime

from ocpi22.util import calculate_partition, get_time_zone

import pytz


class OCPItoOICPConverter:
    def __init__(self, oicp_version: str, ocpi_version: str):
        self.oicp_version = oicp_version
        self.ocpi_version = ocpi_version

    def __convert_to_evse(self, evse: EvseDataRecord) -> Evse:
        return Evse(
            # uid=,
            evse_id=evse.EvseID,
            # status=
            last_updated=evse.lastUpdate,
            # updated=
            # created=
            capabilities=self.get_capabilities(
                evse.AuthenticationModes, evse.ValueAddedServices, evse.PaymentOptions
            ),
        )

    def convert_eroaming_to_locations(
        self, eroaming_data: ERoamingPushEvseData
    ) -> List[Location]:
        operator_evse_data = eroaming_data.OperatorEvseData
        locations_evse_map = self.get_location_evse_map(
            operator_evse_data.EvseDataRecord
        )
        locations = []

        for location_hash_key in locations_evse_map.keys():
            # If the evses are in the same location, data related to the location will be the same
            evse_data_record = locations_evse_map[location_hash_key][0]
            locations.append(
                Location(
                    # todo: Add an identifier for hubject
                    # ocpi_master=,
                    # uid=,
                    # todo: OICP cannot be converted to publish field directly
                    # publish=,
                    name=evse_data_record.ChargingStationNames[0].value
                    if evse_data_record.ChargingStationNames
                    else "",
                    address=self.get_address(evse_data_record.Address),
                    city=evse_data_record.Address.city,
                    postal_code=evse_data_record.Address.postal_code,
                    state=evse_data_record.Address.state,
                    country=evse_data_record.Address.country,
                    latitude=evse_data_record.GeoCoordinates.latitude,
                    longitude=evse_data_record.GeoCoordinates.longitude,
                    lat_partition=calculate_partition(
                        evse_data_record.GeoCoordinates.latitude
                    ),
                    long_partition=calculate_partition(
                        evse_data_record.GeoCoordinates.longitude
                    ),
                    # todo OICP has a boolean for parking_type
                    # parking_type=
                    time_zone=get_time_zone(evse_data_record.TimeZone),
                    last_updated=datetime.now(pytz.utc),
                    updated=datetime.now(pytz.utc),
                    created=datetime.now(pytz.utc),
                    # todo : OICP cannot be directly converted to facilities
                    # facilities=
                    charging_when_closed=evse_data_record.IsOpen24Hours,
                    # todo: Ask from hubject
                    # operator=,
                    # suboperator=,
                    owner=BusinessDetails.objects.get_or_create(
                        name=operator_evse_data.OperatorName
                    ),
                    evses=[
                        self.__convert_to_evse(evse)
                        for evse in locations_evse_map[location_hash_key]
                    ],
                )
            )

        return locations

    def convert(self, ocpi_message: dict) -> dict: ...

    def get_location_evse_map(self, evses: List[EvseDataRecord]) -> dict:
        location_map = defaultdict(list)
        for evse in evses:
            address = f"{evse.address.street}{evse.address.city}{evse.address.postal_code}{evse.address.state}{evse.address.country}"
            location_map[hash(address)].append(evse)
        return location_map

    def get_timezone(self, utc_offset: str):
        """
        >>> oicp_to_ocpi = OCPItoOICPConverter()
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
        # todo finalize address format
        # return f"{address.street}, {address.city}, {address.postal_code}, {address.state}, {address.country}"
        ...

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
