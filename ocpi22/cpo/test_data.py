class LocationData:
    location1 = {
        "quick_url": "http://localhost:8000/api/cpo/v2/location/quick/EKI1/",
        "id": "EKI1",
        "name": "Eki's home charger",
        "address": "Kotikatu 38",
        "city": "Espoo",
        "postal_code": "01234",
        "country": "FIN",
        "time_zone": "Europe/Helsinki",
        "latitude": 60.0,
        "longitude": 30.0,
        "evses": [
            {
                "status_url": "http://localhost:8000/api/cpo/v2/location/quick/EKI1/",
                "uid": "1",
                "connectors": [
                    {
                        "uid": "1",
                        "standard": "IEC_62196_T2",
                        "format": "CABLE",
                        "max_voltage": 233,
                        "max_amperage": 32,
                        "max_electric_power": 22200,
                        "tariff_ids": [
                            "EKI1"
                        ]
                    }
                ],
                "last_updated": "2022-06-18T11:08:03.102160Z"
            },
            {
                "status_url": "http://localhost:8000/api/cpo/v2/location/quick/EKI1/",
                "uid": "2",
                "connectors": [
                    {
                        "uid": "1",
                        "standard": "IEC_62196_T2",
                        "format": "SOCKET",
                        "max_voltage": 232,
                        "max_amperage": 32
                    }
                ],
                "last_updated": "2022-06-18T11:08:03.102160Z"
            },
            {
                "status_url": "http://localhost:8000/api/cpo/v2/location/quick/EKI1/",
                "uid": "12321",
                "connectors": [
                    {
                        "uid": "1",
                        "standard": "IEC_62196_T2",
                        "format": "CABLE",
                        "max_voltage": 233,
                        "max_amperage": 32,
                        "tariff_ids": [
                            "DC50"
                        ]
                    }
                ],
                "last_updated": "2022-06-18T11:08:03.102160Z"
            }
        ]
    }

    location_update1 = {
        "id": "EKI1",
        "evses": [
            {
                "uid": "1",
                "connectors": [
                    {
                        "uid": "1",
                        "format": "SOCKET",
                        "max_electric_power": 11000,
                        "tariff_ids": [
                            "DC50"
                        ]
                    }
                ],
                "last_updated": "2022-06-19T12:13:14"
            }
        ]
    }
