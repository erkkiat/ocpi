from integrations.hubject.schemas import (
    Accessibility,
    AccessibilityLocation,
    ActionType,
    AuthenticationMode,
    CalibrationLawDataAvailability,
    DynamicInfoAvailable,
    PaymentOption,
    Plug,
    PowerType,
    ValueAddedService,
)

from datetime import datetime
import pytz


class ERoamingPushTestData:
    helsinki_eroaming_push_data = {
        "ActionType": ActionType.insert,
        "OperatorEvseData": {
            "OperatorID": "DE*SMP",
            "OperatorName": "Smappee Pvt Ltd.",
            "EvseDataRecord": [
                {
                    "Accessibility": Accessibility.Free_publicly_accessible,
                    "AccessibilityLocation": AccessibilityLocation.OnStreet,
                    "AdditionalInfo": None,
                    "Address": {
                        "City": "Helsinki",
                        "Country": "FIN",
                        "Floor": None,
                        "HouseNum": "1",
                        "ParkingFacility": True,
                        "ParkingSpot": None,
                        "PostalCode": "00100",
                        "Region": None,
                        "Street": "Mannerheimintie",
                        "TimeZone": "UTC+03:00",
                    },
                    "AuthenticationModes": [AuthenticationMode.NFC_RFID_Classic],
                    "CalibrationLawDataAvailability": CalibrationLawDataAvailability.Local,
                    "ChargingFacilities": [
                        {
                            "Amperage": 16,
                            "ChargingModes": None,
                            "Power": 37,
                            "PowerType": PowerType.DC,
                            "Voltage": 230,
                        }
                    ],
                    "ChargingPoolID": None,
                    "ChargingStationId": None,
                    "ChargingStationImage": None,
                    "ChargingStationLocationReference": None,
                    "ChargingStationNames": [
                        {"lang": "en", "value": "Helsinki Supercharger"}
                    ],
                    "ClearinghouseID": None,
                    "DynamicInfoAvailable": DynamicInfoAvailable.auto,
                    "DynamicPowerLevel": None,
                    "EnergySource": None,
                    "EnvironmentalImpact": None,
                    "EvseID": "FI*ABC*E1234*5668",
                    "GeoChargingPointEntrance": {
                        "DecimalDegree": {
                            "Latitude": "60.1695",
                            "Longitude": "24.9354",
                        },
                        "DegreeMinuteSeconds": None,
                        "Google": None,
                    },
                    "GeoCoordinates": {
                        "DecimalDegree": {
                            "Latitude": "60.1695",
                            "Longitude": "24.9354",
                        },
                        "DegreeMinuteSeconds": None,
                        "Google": None,
                    },
                    "HardwareManufacturer": None,
                    "HotlinePhoneNumber": "+3256380211",
                    "HubOperatorID": None,
                    "IsHubjectCompatible": True,
                    "IsOpen24Hours": True,
                    "MaxCapacity": None,
                    "OpeningTimes": None,
                    "PaymentOptions": [PaymentOption.Contract],
                    "Plugs": [Plug.Type_2_Outlet],
                    "RenewableEnergy": False,
                    "SubOperatorName": None,
                    "ValueAddedServices": [ValueAddedService.Reservation],
                    "deltaType": None,
                    "lastUpdate": pytz.utc.localize(
                        datetime(2024, 9, 22, 17, 32, 8, 599540)
                    ),
                }
            ],
        },
    }
