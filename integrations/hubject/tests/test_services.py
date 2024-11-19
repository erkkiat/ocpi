from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import responses
from django.conf import settings
from pydantic_core import PydanticSerializationError
from requests import HTTPError
from responses import matchers

from integrations.hubject.schemas import (
    ActionType,
    OperatorEvseData,
    OperatorID,
    EvseDataRecord,
    EvseID,
    InfoTextType,
    Address,
    GeoCoordinates,
    DecimalDegree,
    Plug,
    ChargingFacility,
    PowerType,
    CalibrationLawDataAvailability,
    AuthenticationMode,
    PaymentOption,
    ValueAddedService,
    Accessibility,
    AccessibilityLocation,
    DynamicInfoAvailable,
)
from integrations.hubject.services import HubjectService


class TestHubjectService:
    __hubject_service = HubjectService()

    @patch("ocpi22.models.location.Location.objects.all")
    @pytest.mark.django_db
    def test_get_operator_evse_dict(
        self,
        mock_locations,
        berlin_location,
        emsdetten_location,
        berlin_op_evse_data,
        emsdetten_op_evse_data,
    ):
        mock_locations.return_value = [berlin_location, emsdetten_location]
        result = self.__hubject_service.get_all_operator_evses()
        print(result[emsdetten_op_evse_data.OperatorID.root])

        assert (
            result[berlin_op_evse_data.OperatorID.root][0]
            == self.expected_berlin_op_evse_data_record()
        )
        assert (
            result[emsdetten_op_evse_data.OperatorID.root][0]
            == self.expected_emsdetten_op_evse_data_record()
        )

    def test_get_evse_full_load_payload_by_operator_id(
        self,
        berlin_op_evse_data,
        emsdetten_op_evse_data,
        berlin_evse_data_record,
        emsdetten_evse_data_record,
    ):
        operator_id = berlin_op_evse_data.OperatorID
        operator_name = berlin_op_evse_data.OperatorName
        op_evse_list = [berlin_op_evse_data, emsdetten_op_evse_data]

        result = self.__hubject_service.get_evse_full_load_payload_by_operator_id(
            operator_id, op_evse_list
        )

        assert result.ActionType == ActionType.fullLoad
        assert result.OperatorEvseData.OperatorID == operator_id
        assert result.OperatorEvseData.OperatorName == operator_name
        assert result.OperatorEvseData.EvseDataRecord == [
            berlin_evse_data_record,
            emsdetten_evse_data_record,
        ]

    @responses.activate
    def test_post_evse_full_load(
        self, evse_full_load_payload, hubject_successful_response
    ):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            json=hubject_successful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.__hubject_service.post_evse_full_load(
            operator_id, evse_full_load_payload
        )

        assert result == hubject_successful_response

    @responses.activate
    def test_post_evse_full_load_unsuccessful_response(
        self, evse_full_load_payload, hubject_unsuccessful_response
    ):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        # edit the payload to generate a unsuccessful response from the hubject APIs
        evse_full_load_payload.OperatorEvseData.EvseDataRecord[
            0
        ].ValueAddedServices = []

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            json=hubject_unsuccessful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        result = self.__hubject_service.post_evse_full_load(
            operator_id, evse_full_load_payload
        )

        assert result == hubject_unsuccessful_response

    @responses.activate
    def test_execute_evse_full_load_http_error(self, evse_full_load_payload):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            body=HTTPError("HTTP request failed"),
            status=500,
        )

        with pytest.raises(HTTPError):
            service = HubjectService()
            result = service.post_evse_full_load(operator_id, evse_full_load_payload)

            assert result == {
                "success": False,
                "errorType": "HTTP request failed",
                "error": "HTTP request failed",
            }

    def test_execute_evse_full_load_pydantic_error(self):
        operator_id = "DE+MSP"

        payload_mock = MagicMock()
        payload_mock.model_dump_json.side_effect = PydanticSerializationError(
            "serialization error"
        )

        result = self.__hubject_service.post_evse_full_load(operator_id, payload_mock)

        assert result == {
            "success": False,
            "errorType": "Pydantic validation failed",
            "error": "serialization error",
        }

    def expected_berlin_op_evse_data_record(self):
        return OperatorEvseData(
            OperatorID=OperatorID(root="DE*SMP"),
            OperatorName="Smappee Pvt Ltd",
            EvseDataRecord=[
                EvseDataRecord(
                    deltaType=None,
                    lastUpdate=datetime(
                        2024, 9, 22, 17, 32, 8, 599540, tzinfo=timezone.utc
                    ),
                    EvseID=EvseID(root="AW*ABC*Eberlinevseuid"),
                    ChargingPoolID=None,
                    ChargingStationId=None,
                    ChargingStationNames=[
                        InfoTextType(lang="en", value="Berlin Location")
                    ],
                    HardwareManufacturer=None,
                    ChargingStationImage=None,
                    SubOperatorName=None,
                    Address=Address(
                        Country="DEU",
                        City="Wallenhorst",
                        Street="Ansgarstr.",
                        PostalCode="",
                        HouseNum="4",
                        Floor=None,
                        Region=None,
                        ParkingFacility=True,
                        ParkingSpot=None,
                        TimeZone="UTC+01:00",
                    ),
                    GeoCoordinates=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="0.000000", Latitude="0.000000"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    Plugs=[Plug.Type_2_Outlet],
                    DynamicPowerLevel=None,
                    ChargingFacilities=[
                        ChargingFacility(
                            PowerType=PowerType.AC_3_PHASE,
                            Voltage=0,
                            Amperage=16,
                            Power=12,
                            ChargingModes=None,
                        )
                    ],
                    RenewableEnergy=False,
                    EnergySource=None,
                    EnvironmentalImpact=None,
                    CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
                    AuthenticationModes=[AuthenticationMode.No_Authentication_Required],
                    MaxCapacity=None,
                    PaymentOptions=[PaymentOption.Contract],
                    ValueAddedServices=[ValueAddedService.None_],
                    Accessibility=Accessibility.Free_publicly_accessible,
                    AccessibilityLocation=AccessibilityLocation.OnStreet,
                    HotlinePhoneNumber="+3256380211",
                    AdditionalInfo=None,
                    ChargingStationLocationReference=None,
                    GeoChargingPointEntrance=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="0.000000", Latitude="0.000000"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    IsOpen24Hours=True,
                    OpeningTimes=None,
                    HubOperatorID=None,
                    ClearinghouseID=None,
                    IsHubjectCompatible=False,
                    DynamicInfoAvailable=DynamicInfoAvailable.false,
                )
            ],
        )

    def expected_emsdetten_op_evse_data_record(self):
        return OperatorEvseData(
            OperatorID=OperatorID(root="DE*EMP"),
            OperatorName="Smappee Pvt Ltd",
            EvseDataRecord=[
                EvseDataRecord(
                    deltaType=None,
                    lastUpdate=datetime(
                        2024, 9, 22, 17, 32, 8, 599540, tzinfo=timezone.utc
                    ),
                    EvseID=EvseID(root="AW*ABC*EEemsdettenevseuid"),
                    ChargingPoolID=None,
                    ChargingStationId=None,
                    ChargingStationNames=[
                        InfoTextType(lang="en", value="Emsdetten Location")
                    ],
                    HardwareManufacturer=None,
                    ChargingStationImage=None,
                    SubOperatorName=None,
                    Address=Address(
                        Country="DEU",
                        City="Emsdetten",
                        Street="dring",
                        PostalCode="38170",
                        HouseNum="25",
                        Floor=None,
                        Region=None,
                        ParkingFacility=True,
                        ParkingSpot=None,
                        TimeZone="UTC+01:00",
                    ),
                    GeoCoordinates=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="47.662249", Latitude="9.360922"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    Plugs=[Plug.Type_2_Outlet],
                    DynamicPowerLevel=None,
                    ChargingFacilities=[
                        ChargingFacility(
                            PowerType=PowerType.AC_3_PHASE,
                            Voltage=0,
                            Amperage=16,
                            Power=1,
                            ChargingModes=None,
                        )
                    ],
                    RenewableEnergy=False,
                    EnergySource=None,
                    EnvironmentalImpact=None,
                    CalibrationLawDataAvailability=CalibrationLawDataAvailability.Local,
                    AuthenticationModes=[AuthenticationMode.No_Authentication_Required],
                    MaxCapacity=None,
                    PaymentOptions=[PaymentOption.Contract],
                    ValueAddedServices=[ValueAddedService.None_],
                    Accessibility=Accessibility.Free_publicly_accessible,
                    AccessibilityLocation=AccessibilityLocation.OnStreet,
                    HotlinePhoneNumber="+3256380211",
                    AdditionalInfo=None,
                    ChargingStationLocationReference=None,
                    GeoChargingPointEntrance=GeoCoordinates(
                        Google=None,
                        DecimalDegree=DecimalDegree(
                            Longitude="47.662249", Latitude="9.360922"
                        ),
                        DegreeMinuteSeconds=None,
                    ),
                    IsOpen24Hours=True,
                    OpeningTimes=None,
                    HubOperatorID=None,
                    ClearinghouseID=None,
                    IsHubjectCompatible=False,
                    DynamicInfoAvailable=DynamicInfoAvailable.false,
                )
            ],
        )
