from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal

import pytz


class CredentialsData:
    credentials_post_response = {
        "data": {
            "roles": [
                {
                    "business_details": {"name": "BestCompany.EU", "website": None},
                    "country_code": "FI",
                    "party_id": "CPO",
                    "role": "CPO",
                },
                {
                    "business_details": {"name": "BestCompany.EU", "website": None},
                    "country_code": "FI",
                    "party_id": "MSP",
                    "role": "EMSP",
                },
            ],
            "token": "12345",
            "url": "http://testserver.test/ocpi/versions/",
        },
        "status_code": 1000,
        "status_message": "Success",
        "timestamp": "2022-01-01T12:00:00Z",
    }

    registered_credentials = {
        "connection_status": "CONNECTED",
        "created": datetime(2022, 1, 8, 7, 56, 40, 267000, tzinfo=timezone.utc),
        "id": 2,
        "last_connection": datetime(2022, 1, 1, 12, 0, tzinfo=timezone.utc),
        "last_updated": datetime(2022, 1, 13, 18, 57, 11, 300000, tzinfo=timezone.utc),
        "ours": "12345",
        "theirs": "9e80a9c4-28be-11e9-b210-d663bd873d93",
        "meter_value_frequency": None,
        "token_a": "",
        "updated": datetime(2022, 1, 1, 12, 0, tzinfo=timezone.utc),
        "url": "https://localhost/versions/",
        "valid": True,
        "version": "221",
        "allowed_locations": [],
        "client_certificate_name": "",
        "private_key_name": "",
        "ca_certificate_name": "",
    }

    expected_versions_response = {
        "data": [
            {"url": "http://testserver.test/ocpi/2.2/", "version": "2.2"},
            {"url": "http://testserver.test/ocpi/2.2.1/", "version": "2.2.1"},
        ],
        "status_code": 1000,
        "status_message": "Success",
        "timestamp": "2022-01-01T12:00:00Z",
    }

    expected_credentials_response = {
        "data": {
            "roles": [
                {
                    "business_details": {"name": "SolidRoam CPO", "website": ""},
                    "country_code": "FI",
                    "party_id": "CPO",
                    "role": "CPO",
                },
                {
                    "business_details": {"name": "SolidRoam CPO", "website": ""},
                    "country_code": "FI",
                    "party_id": "MSP",
                    "role": "EMSP",
                },
            ],
            "token": "BF60351F296E9E1B339646C8B57338BFE84B61C18E50BCBE822A72D8DDC60A26",
            "url": "http://testserver.test/ocpi/versions/",
        },
        "status_code": 1000,
        "status_message": "Success",
        "timestamp": "2022-01-01T12:00:00Z",
    }

    example = {
        "token": "9e80a9c4-28be-11e9-b210-d663bd873d93",
        "url": "https://localhost/versions/",
        "roles": [
            {
                "role": "CPO",
                "party_id": "EXA",
                "country_code": "NL",
                "business_details": {"name": "Example Operator"},
                "logo": {
                    "url": "https://localhost/img/logo.jpg",
                    "thumbnail": "https://localhost/img/logo_thumb.jpg",
                    "category": "OPERATOR",
                    "type": "jpeg",
                    "width": 512,
                    "height": 512,
                },
            },
            {
                "role": "EMSP",
                "party_id": "EXA",
                "country_code": "NL",
                "business_details": {"name": "Example Provider"},
            },
        ],
    }

    ocpi_endpoints_response = {
        "version": "2.2",
        "endpoints": [
            {
                "identifier": "credentials",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/credentials",
            },
            {
                "identifier": "credentials",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/credentials",
            },
            {
                "identifier": "locations",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/locations",
            },
            {
                "identifier": "locations",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/locations",
            },
            {
                "identifier": "tokens",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/tokens",
            },
            {
                "identifier": "tokens",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/tokens",
            },
            {
                "identifier": "tariffs",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/tariffs",
            },
            {
                "identifier": "tariffs",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/tariffs",
            },
            {
                "identifier": "sessions",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/sessions",
            },
            {
                "identifier": "sessions",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/sessions",
            },
            {
                "identifier": "cdrs",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/cdrs",
            },
            {
                "identifier": "cdrs",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/cdrs",
            },
            {
                "identifier": "commands",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/commands",
            },
        ],
    }

    ocpi_endpoints_response_221 = {
        "version": "2.2.1",
        "endpoints": [
            {
                "identifier": "credentials",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/credentials",
            },
            {
                "identifier": "credentials",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/credentials",
            },
            {
                "identifier": "locations",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/locations",
            },
            {
                "identifier": "locations",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/locations",
            },
            {
                "identifier": "tokens",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/tokens",
            },
            {
                "identifier": "tokens",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/tokens",
            },
            {
                "identifier": "tariffs",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/tariffs",
            },
            {
                "identifier": "tariffs",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/tariffs",
            },
            {
                "identifier": "sessions",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/sessions",
            },
            {
                "identifier": "sessions",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/sessions",
            },
            {
                "identifier": "cdrs",
                "role": "SENDER",
                "url": "http://localhost/ocpi/2.2.1/cdrs",
            },
            {
                "identifier": "cdrs",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/cdrs",
            },
            {
                "identifier": "commands",
                "role": "RECEIVER",
                "url": "http://localhost/ocpi/2.2.1/commands",
            },
        ],
    }


expected_get_responses = {
    "http://localhost:8001/ocpi/2.2.1/tariffs/?limit=3": {
        "data": [
            {
                "country_code": "FI",
                "currency": "EUR",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/000/T2',
                "elements": [
                    {
                        "price_components": [
                            {"price": 0.26, "step_size": 1, "type": "ENERGY"}
                        ]
                    }
                ],
                "id": "T2",
                "last_updated": "2022-01-08T07:52:37Z",
                "party_id": "000",
                "tariff_alt_text": [{"language": "EN", "text": "0,26€/kWh"}],
                "type": "REGULAR",
            },
            {
                "country_code": "FI",
                "currency": "EUR",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/000/T3',
                "elements": [
                    {
                        "price_components": [
                            {"price": 2.0, "step_size": 1, "type": "ENERGY"}
                        ]
                    }
                ],
                "id": "T3",
                "last_updated": "2022-01-08T07:52:37Z",
                "party_id": "000",
                "tariff_alt_text": [{"language": "EN", "text": "2€/kWh"}],
                "type": "REGULAR",
            },
            {
                "country_code": "FI",
                "currency": "EUR",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/000/T4',
                "elements": [
                    {
                        "price_components": [
                            {"price": 2.0, "step_size": 1, "type": "ENERGY"}
                        ]
                    }
                ],
                "id": "T4",
                "last_updated": "2022-01-08T07:52:37Z",
                "party_id": "000",
                "tariff_alt_text": [{"language": "EN", "text": "2€/kWh"}],
                "type": "REGULAR",
            },
        ],
        "status_code": 1000,
        "timestamp": "2022-01-01T12:00:00Z",
    },
    "http://testserver/ocpi/2.2.1/tariffs/?limit=3&offset=3": {
        "data": [
            {
                "country_code": "FI",
                "currency": "EUR",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/000/TTYPE2',
                "elements": [
                    {
                        "price_components": [
                            {
                                "price": 0.22,
                                "step_size": 1,
                                "type": "ENERGY",
                                "vat": 24.0,
                            }
                        ]
                    }
                ],
                "id": "TTYPE2",
                "party_id": "000",
                "tariff_alt_text": [{"language": "EN", "text": "0,22€/kWh"}],
                "type": "REGULAR",
            },
            {
                "country_code": "FI",
                "currency": "EUR",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/000/TCCS',
                "elements": [
                    {
                        "price_components": [
                            {"price": 0.3, "step_size": 1, "type": "ENERGY"}
                        ]
                    }
                ],
                "id": "TCCS",
                "party_id": "000",
                "tariff_alt_text": [{"language": "EN", "text": "0,30€/kWh"}],
                "type": "REGULAR",
            },
            {
                "country_code": "FI",
                "currency": "EUR",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/000/TCHADEMO',
                "elements": [
                    {
                        "price_components": [
                            {"price": 0.3, "step_size": 1, "type": "ENERGY"}
                        ]
                    }
                ],
                "id": "TCHADEMO",
                "party_id": "000",
                "tariff_alt_text": [{"language": "EN", "text": "0,30€/kWh"}],
                "type": "REGULAR",
            },
        ],
        "status_code": 1000,
        "timestamp": "2022-01-01T12:00:00Z",
    },
    "http://localhost:8001/ocpi/2.2.1/tokens/?limit=3": {
        "data": [
            {
                "contract_id": "CONTRACT3",
                "country_code": "FI",
                "default_profile_type": "FAST",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tokens/FI/001/T1',
                "issuer": "EKI",
                "last_updated": "2017-12-10T17:25:10Z",
                "party_id": "MSP",
                "type": "RFID",
                "uid": "T1",
                "valid": True,
                "visual_number": "12345",
                "whitelist": "NEVER",
            },
            {
                "contract_id": "CONTRACT6",
                "country_code": "FI",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tokens/FI/000/T2',
                "issuer": "eki",
                "last_updated": "2022-01-09T14:11:32Z",
                "party_id": "000",
                "type": "RFID",
                "uid": "T2",
                "valid": True,
                "visual_number": "123B",
                "whitelist": "NEVER",
            },
            {
                "contract_id": "CONTRACT_F",
                "country_code": "FI",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tokens/FI/000/T7',
                "issuer": "eki",
                "last_updated": "2022-01-10T07:00:18Z",
                "party_id": "000",
                "type": "APP_USER",
                "uid": "T7",
                "valid": True,
                "visual_number": "123C",
                "whitelist": "NEVER",
            },
        ],
        "status_code": 1000,
        "timestamp": "2022-01-01T12:00:00Z",
    },
    "http://testserver/ocpi/2.2.1/tokens/?limit=3&offset=3": {
        "data": [
            {
                "contract_id": "INTERNAL 1",
                "country_code": "FI",
                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/tokens/FI/001/FI*001*T*ADMIN*TOKEN',
                "issuer": "FI*001",
                "last_updated": "2022-01-12T19:44:39Z",
                "party_id": "MSP",
                "type": "OTHER",
                "uid": "FI*001*T*ADMIN*TOKEN",
                "valid": True,
            }
        ],
        "status_code": 1000,
        "timestamp": "2022-01-01T12:00:00Z",
    },
    "http://localhost:8001/ocpi/2.2.1/locations/?limit=3": dict(
        [
            (
                "data",
                [
                    {
                        "address": "Warsawskaya 1",
                        "city": "Warsaw",
                        "coordinates": {
                            "latitude": "40.000000",
                            "longitude": "10.000000",
                        },
                        "country": "POL",
                        "country_code": "FI",
                        # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/WARSAW-1',
                        "evses": [
                            {
                                "capabilities": [
                                    "REMOTE_START_STOP_CAPABLE",
                                    "START_SESSION_CONNECTOR_REQUIRED",
                                ],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "1",
                                        "last_updated": "2022-01-08T14:05:06Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                    },
                                    {
                                        "format": "CABLE",
                                        "id": "2",
                                        "last_updated": "2022-01-08T14:05:06Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                    },
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/WARSAW-1/2',
                                "evse_id": "PL*TSL*EWARSAW1",
                                "last_updated": "2022-01-08T14:05:06Z",
                                "status": "AVAILABLE",
                                "uid": "2",
                            }
                        ],
                        "facilities": ["HOTEL", "RESTAURANT"],
                        "id": "WARSAW-1",
                        "last_updated": "2022-01-08T14:05:06Z",
                        "name": "Warsaw Supercharger",
                        "operator": {
                            "name": "Tesla",
                            "website": "http://www.tesla.com/",
                        },
                        "parking_type": "UNDERGROUND_GARAGE",
                        "party_id": "000",
                        "publish": True,
                        "time_zone": "Europe/Warsaw",
                    },
                    {
                        "address": "Vierumäki 2",
                        "city": "Lahti",
                        "coordinates": {
                            "latitude": "61.000000",
                            "longitude": "31.000000",
                        },
                        "country": "FIN",
                        "country_code": "FI",
                        # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/VM-1',
                        "evses": [
                            {
                                "capabilities": ["CREDIT_CARD_PAYABLE"],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "1",
                                        "last_updated": "2022-01-08T14:15:25Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/VM-1/VM-1',
                                "evse_id": "FI*TSL*EVM1",
                                "last_updated": "2022-01-08T14:15:25Z",
                                "status": "AVAILABLE",
                                "uid": "VM-1",
                            }
                        ],
                        "facilities": ["RESTAURANT", "SUPERMARKET"],
                        "id": "VM-1",
                        "last_updated": "2022-01-08T14:15:25Z",
                        "name": "Vierumäki Supercharger",
                        "operator": {
                            "name": "Tesla",
                            "website": "http://www.tesla.com/",
                        },
                        "parking_type": "PARKING_LOT",
                        "party_id": "000",
                        "publish": True,
                        "time_zone": "Europe/Helsinki",
                    },
                    {
                        "address": "Oulu 1",
                        "city": "Oulu",
                        "coordinates": {
                            "latitude": "64.000000",
                            "longitude": "27.000000",
                        },
                        "country": "FIN",
                        "country_code": "FI",
                        # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/001/TSL-OULU',
                        "evses": [
                            {
                                "capabilities": ["DEBIT_CARD_PAYABLE"],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "1",
                                        "last_updated": "2022-01-08T14:37:27Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 150000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/001/TSL-OULU/TSL-OULU',
                                "evse_id": "FI*TSL*EOULU1",
                                "last_updated": "2022-01-08T14:37:27Z",
                                "status": "AVAILABLE",
                                "uid": "TSL-OULU",
                            },
                            {
                                "capabilities": ["RFID_READER"],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "b3e536ab1cf14d18bc3824e99a809384",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/001/TSL-OULU/NEWEVSE',
                                "evse_id": "FI*TSL*EOULU2",
                                "status": "AVAILABLE",
                                "uid": "NEWEVSE",
                            },
                        ],
                        "facilities": ["HOTEL", "RESTAURANT", "MALL"],
                        "id": "TSL-OULU",
                        "name": "Supercharger Oulu",
                        "operator": {
                            "name": "Tesla",
                            "website": "http://www.tesla.com",
                        },
                        "parking_type": "UNDERGROUND_GARAGE",
                        "party_id": "000",
                        "publish": True,
                        "time_zone": "Europe/Helsinki",
                    },
                ],
            ),
            ("status_code", 1000),
            ("timestamp", "2022-01-01T12:00:00"),
        ]
    ),
    "http://testserver/ocpi/2.2.1/locations/?limit=3&offset=3": dict(
        [
            (
                "data",
                [
                    {
                        "address": "Vaasa 1",
                        "city": "Vaasa",
                        "coordinates": {
                            "latitude": "63.000000",
                            "longitude": "31.000000",
                        },
                        "country": "FIN",
                        "country_code": "FI",
                        # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/VAASA-1',
                        "evses": [
                            {
                                "capabilities": ["CHARGING_PROFILE_CAPABLE"],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "1",
                                        "last_updated": "2022-01-08T14:55:22Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/VAASA-1/1',
                                "evse_id": "FI*TSL*EVAASA1",
                                "last_updated": "2022-01-08T14:55:22Z",
                                "status": "AVAILABLE",
                                "uid": "1",
                            }
                        ],
                        "facilities": ["RESTAURANT"],
                        "id": "VAASA-1",
                        "last_updated": "2022-01-08T14:55:22Z",
                        "name": "Vaasa Supercharger",
                        "operator": {
                            "name": "Tesla",
                            "website": "http://www.tesla.com/",
                        },
                        "parking_type": "PARKING_GARAGE",
                        "party_id": "000",
                        "publish": True,
                        "time_zone": "Europe/Helsinki",
                    },
                    {
                        "address": "Paimio 2",
                        "city": "Salo",
                        "coordinates": {
                            "latitude": "60.000000",
                            "longitude": "29.000000",
                        },
                        "country": "FIN",
                        "country_code": "FI",
                        # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/PAIMIO-1',
                        "evses": [
                            {
                                "capabilities": [
                                    "RFID_READER",
                                    "DEBIT_CARD_PAYABLE",
                                    "CHARGING_PROFILE_CAPABLE",
                                    "CHARGING_PREFERENCES_CAPABLE",
                                ],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "1",
                                        "last_updated": "2022-01-08T15:06:54Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/PAIMIO-1/PA-1',
                                "evse_id": "FI*TSL*EPAIMIO1",
                                "last_updated": "2022-01-08T15:06:54Z",
                                "status": "AVAILABLE",
                                "uid": "PA-1",
                            }
                        ],
                        "facilities": ["RESTAURANT", "CAFE", "SUPERMARKET"],
                        "id": "PAIMIO-1",
                        "last_updated": "2022-01-08T15:06:54Z",
                        "name": "Paimio Supercharger",
                        "operator": {
                            "name": "Tesla",
                            "website": "http://www.tesla.com/",
                        },
                        "parking_type": "ALONG_MOTORWAY",
                        "party_id": "000",
                        "publish": True,
                        "time_zone": "Europe/Helsinki",
                    },
                    {
                        "address": "Helsinki 12",
                        "city": "Helsinki",
                        "coordinates": {
                            "latitude": "60.000000",
                            "longitude": "30.000000",
                        },
                        "country": "FIN",
                        "country_code": "FI",
                        # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/HELSINKI-1',
                        "evses": [
                            {
                                "capabilities": ["RFID_READER"],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "3050",
                                        "last_updated": "2022-01-09T10:50:58Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                        "tariff_ids": ["T4"],
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/HELSINKI-1/HELSINKI-1',
                                "evse_id": "FI*TSL*EHELSINKI1",
                                "last_updated": "2022-01-09T10:50:58Z",
                                "status": "AVAILABLE",
                                "uid": "HELSINKI-1",
                            },
                            {
                                "capabilities": ["CHARGING_PROFILE_CAPABLE"],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "1",
                                        "last_updated": "2022-01-09T06:38:44Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                        "tariff_ids": ["T2"],
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/HELSINKI-1/HELSINKI-2',
                                "evse_id": "FI*TSL*EHELSINKI2",
                                "last_updated": "2022-01-09T06:38:44Z",
                                "status": "AVAILABLE",
                                "uid": "HELSINKI-2",
                            },
                            {
                                "capabilities": ["PED_TERMINAL"],
                                "connectors": [
                                    {
                                        "format": "CABLE",
                                        "id": "1",
                                        "last_updated": "2022-01-09T10:48:07Z",
                                        "max_amperage": 375,
                                        "max_electric_power": 450000,
                                        "max_voltage": 400,
                                        "power_type": "DC",
                                        "standard": "TESLA_S",
                                        "tariff_ids": ["T2"],
                                    }
                                ],
                                # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/HELSINKI-1/HELSINKI-3',
                                "evse_id": "FI*TSL*EHELSINKI3",
                                "last_updated": "2022-01-09T10:48:07Z",
                                "status": "AVAILABLE",
                                "uid": "HELSINKI-3",
                            },
                        ],
                        "facilities": ["HOTEL"],
                        "id": "HELSINKI-1",
                        "last_updated": "2022-01-09T10:48:07Z",
                        "name": "Helsinki Supercharger",
                        "operator": {
                            "name": "Tesla",
                            "website": "http://www.tesla.com/",
                        },
                        "owner": {"name": "Tesla", "website": "http://www.tesla.com/"},
                        "parking_type": "PARKING_LOT",
                        "party_id": "000",
                        "publish": True,
                        "suboperator": {
                            "name": "ChargerHub.eu",
                            "website": "http://www.chargerhub.eu/",
                        },
                        "time_zone": "Europe/Helsinki",
                    },
                ],
            ),
            ("status_code", 1000),
            ("timestamp", "2022-01-01T12:00:00"),
        ]
    ),
    "http://testserver/ocpi/2.2.1/locations/?limit=3&offset=6": dict(
        [
            (
                "data",
                [
                    {
                        "address": "Stockholm 1",
                        "city": "Stockholm",
                        "coordinates": {
                            "latitude": "60.000000",
                            "longitude": "25.000000",
                        },
                        "country": "SWE",
                        "country_code": "FI",
                        # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/locations/FI/000/STOCKHOLM-1',
                        "facilities": ["RESTAURANT"],
                        "id": "STOCKHOLM-1",
                        "last_updated": "2022-01-09T08:56:12Z",
                        "name": "Stockholm Supercharger",
                        "operator": {
                            "name": "Tesla",
                            "website": "http://www.tesla.com",
                        },
                        "parking_type": "ALONG_MOTORWAY",
                        "party_id": "000",
                        "publish": True,
                        "time_zone": "Europe/Stockholm",
                    }
                ],
            ),
            ("status_code", 1000),
            ("timestamp", "2022-01-01T12:00:00"),
        ]
    ),
}

expected_get_headers = {
    "http://localhost:8001/ocpi/2.2.1/tariffs/?limit=3": {
        "Allow": "GET, PUT, DELETE, HEAD, OPTIONS",
        "Content-Length": "835",
        "Content-Language": "en",
        "Content-Type": "application/json",
        "Link": "<http://testserver/ocpi/2.2.1/tariffs/?limit=3&offset=3; "
        'rel="next">',
        "Vary": "Accept, Accept-Language, Cookie, origin",
        "X-Frame-Options": "DENY",
        "X-Limit": "50",
        "X-Total-Count": "6",
    },
    "http://testserver/ocpi/2.2.1/tariffs/?limit=3&offset=3": {
        "Allow": "GET, PUT, DELETE, HEAD, OPTIONS",
        "Content-Length": "756",
        "Content-Language": "en",
        "Content-Type": "application/json",
        "Vary": "Accept, Accept-Language, Cookie, origin",
        "X-Frame-Options": "DENY",
        "X-Limit": "50",
        "X-Total-Count": "6",
    },
    "http://localhost:8001/ocpi/2.2.1/tokens/?limit=3": {
        "Allow": "GET, PUT, PATCH, HEAD, OPTIONS",
        "Content-Length": "894",
        "Content-Language": "en",
        "Content-Type": "application/json",
        "Link": '<http://testserver/ocpi/2.2.1/tokens/?limit=3&offset=3; rel="next">',
        "Vary": "Accept, Accept-Language, Cookie, origin",
        "X-Frame-Options": "DENY",
        "X-Limit": "50",
        "X-Total-Count": "4",
    },
    "http://testserver/ocpi/2.2.1/tokens/?limit=3&offset=3": {
        "Allow": "GET, PUT, PATCH, HEAD, OPTIONS",
        "Content-Length": "1100",
        "Content-Language": "en",
        "Content-Type": "application/json",
        "Vary": "Accept, Accept-Language, Cookie, origin",
        "X-Frame-Options": "DENY",
        "X-Limit": "50",
        "X-Total-Count": "4",
    },
    "http://localhost:8001/ocpi/2.2.1/locations/?limit=3": {
        "Allow": "GET, PUT, PATCH, HEAD, OPTIONS",
        "Content-Length": "3309",
        "Content-Language": "en",
        "Content-Type": "application/json",
        "Link": "<http://testserver/ocpi/2.2.1/locations/?limit=3&offset=3; "
        'rel="next">',
        "Vary": "Accept, Accept-Language, Cookie, origin",
        "X-Frame-Options": "DENY",
        "X-Limit": "50",
        "X-Total-Count": "7",
    },
    "http://testserver/ocpi/2.2.1/locations/?limit=3&offset=3": {
        "Allow": "GET, PUT, PATCH, HEAD, OPTIONS",
        "Content-Length": "3885",
        "Content-Language": "en",
        "Content-Type": "application/json",
        "Link": "<http://testserver/ocpi/2.2.1/locations/?limit=3&offset=6; "
        'rel="next">',
        "Vary": "Accept, Accept-Language, Cookie, origin",
        "X-Frame-Options": "DENY",
        "X-Limit": "50",
        "X-Total-Count": "7",
    },
    "http://testserver/ocpi/2.2.1/locations/?limit=3&offset=6": {
        "Allow": "GET, PUT, PATCH, HEAD, OPTIONS",
        "Content-Length": "558",
        "Content-Language": "en",
        "Content-Type": "application/json",
        "Vary": "Accept, Accept-Language, Cookie, origin",
        "X-Frame-Options": "DENY",
        "X-Limit": "50",
        "X-Total-Count": "7",
    },
}


class ExpectedSessionUpdateResults:
    update1 = {  # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/12345',
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "cdr_token": OrderedDict(
            [("uid", "T1"), ("type", "RFID"), ("contract_id", "CONTRACT3")]
        ),
        "charging_periods": [
            OrderedDict(
                [
                    ("start_date_time", "2019-06-23T08:16:02Z"),
                    ("tariff", None),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "3000.0000")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "80.0000")]
                            ),
                        ],
                    ),
                ]
            )
        ],
        "connector_id": "1",
        "country_code": "FI",
        "currency": "EUR",
        "evse_uid": "1",
        "kwh": 18.0,
        "last_updated": "2019-06-23T08:22:22Z",
        "location_id": "WARSAW-1",
        "party_id": "CPO",
        "start_date_time": "2022-01-01T12:00:00Z",
        "status": "PENDING",
        "total_cost": OrderedDict([("excl_vat", 1.0), ("incl_vat", 1.2)]),
        "id": "12345",
    }

    webhook1 = {
        "country_code": "FI",
        "party_id": "CPO",
        "uid": "12345",
        "start_date_time": "2022-01-01T12:00:00Z",
        "kwh": 18.0,
        "charging_periods": [
            OrderedDict(
                [
                    ("start_date_time", "2019-06-23T08:16:02Z"),
                    ("tariff", None),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "3000.0000")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "80.0000")]
                            ),
                        ],
                    ),
                ]
            )
        ],
        "total_time": "0.00",
        "display_total_time": "0 s",
        "cdr_token": OrderedDict(
            [("uid", "T1"), ("type", "RFID"), ("contract_id", "CONTRACT3")]
        ),
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "location_id": "WARSAW-1",
        "evse_uid": "1",
        "connector_id": "1",
        "currency": "EUR",
        "total_cost": OrderedDict([("excl_vat", 1.0), ("incl_vat", 1.2)]),
        "status": "PENDING",
        "display_status": "Pending",
        "last_updated": "2019-06-23T08:22:22Z",
    }

    update2 = {  # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/12345',
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "cdr_token": OrderedDict(
            [("uid", "T1"), ("type", "RFID"), ("contract_id", "CONTRACT3")]
        ),
        "charging_periods": [
            OrderedDict(
                [
                    ("start_date_time", "2019-06-23T08:16:02Z"),
                    ("tariff", None),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "3000.0000")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "80.0000")]
                            ),
                        ],
                    ),
                ]
            ),
            OrderedDict(
                [
                    ("start_date_time", "2019-06-23T08:35:35Z"),
                    ("tariff", None),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "4000.0000")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "90.0000")]
                            ),
                        ],
                    ),
                ]
            ),
        ],
        "connector_id": "1",
        "country_code": "FI",
        "currency": "EUR",
        "evse_uid": "1",
        "kwh": 20.0,
        "last_updated": "2019-06-23T08:35:34Z",
        "location_id": "WARSAW-1",
        "party_id": "CPO",
        "start_date_time": "2022-01-01T12:00:00Z",
        "status": "PENDING",
        "total_cost": OrderedDict([("excl_vat", 1.1), ("incl_vat", 1.3)]),
        "id": "12345",
    }

    webhook2 = {
        "country_code": "FI",
        "party_id": "CPO",
        "uid": "12345",
        "start_date_time": "2022-01-01T12:00:00Z",
        "kwh": 20.0,
        "charging_periods": [
            OrderedDict(
                [
                    ("start_date_time", "2019-06-23T08:16:02Z"),
                    ("tariff", None),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "3000.0000")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "80.0000")]
                            ),
                        ],
                    ),
                ]
            ),
            OrderedDict(
                [
                    ("start_date_time", "2019-06-23T08:35:35Z"),
                    ("tariff", None),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "4000.0000")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "90.0000")]
                            ),
                        ],
                    ),
                ]
            ),
        ],
        "total_time": "0.00",
        "display_total_time": "0 s",
        "cdr_token": OrderedDict(
            [("uid", "T1"), ("type", "RFID"), ("contract_id", "CONTRACT3")]
        ),
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "location_id": "WARSAW-1",
        "evse_uid": "1",
        "connector_id": "1",
        "currency": "EUR",
        "total_cost": OrderedDict([("excl_vat", 1.1), ("incl_vat", 1.3)]),
        "status": "PENDING",
        "display_status": "Pending",
        "last_updated": "2019-06-23T08:35:34Z",
    }


class CdrMessages:
    test_transactions_rfid = {
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "cdr_location": OrderedDict(
            [
                ("id", "HELSINKI-1"),
                ("address", "Helsinki 12"),
                ("name", "Helsinki Supercharger"),
                ("city", "Helsinki"),
                ("postal_code", "-"),
                ("country", "FIN"),
                (
                    "coordinates",
                    OrderedDict(
                        [("latitude", "60.000000"), ("longitude", "30.000000")]
                    ),
                ),
                ("evse_uid", "HELSINKI-1"),
                ("evse_id", "FI*TSL*EHELSINKI1"),
                ("connector_id", "3050"),
                ("connector_standard", "TESLA_S"),
                ("connector_format", "CABLE"),
                ("connector_power_type", "DC"),
            ]
        ),
        "cdr_token": OrderedDict(
            [("uid", "EKI1"), ("type", "RFID"), ("contract_id", "DE8ACC12E46L89")]
        ),
        "country_code": "FI",
        "credit": False,
        "currency": "EUR",
        "end_date_time": "2022-05-19T18:12:56Z",
        "id": "CDR2",
        "last_updated": "2022-05-19T18:12:56Z",
        "party_id": "CPO",
        "session_id": "test-transactions",
        "start_date_time": "2022-05-19T18:12:55Z",
        "tariffs": [
            OrderedDict(
                [
                    ("id", "EKI1"),
                    (
                        "elements",
                        [
                            OrderedDict(
                                [
                                    (
                                        "price_components",
                                        [
                                            OrderedDict(
                                                [
                                                    ("type", "ENERGY"),
                                                    ("price", 0.5),
                                                    ("vat", 24.0),
                                                    ("step_size", 0),
                                                ]
                                            )
                                        ],
                                    )
                                ]
                            )
                        ],
                    ),
                    (
                        "tariff_alt_text",
                        [OrderedDict([("language", "EN"), ("text", "0,50€/kWh")])],
                    ),
                    ("country_code", "FI"),
                    ("party_id", "000"),
                    ("currency", "EUR"),
                ]
            )
        ],
        "total_cost": OrderedDict([("excl_vat", 50.0), ("incl_vat", 62.0)]),
        "total_energy": 100.0,
        "total_time": 0.0,
    }
    test_transactions_app_id = {
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "cdr_location": OrderedDict(
            [
                ("id", "HELSINKI-1"),
                ("address", "Helsinki 12"),
                ("name", "Helsinki Supercharger"),
                ("city", "Helsinki"),
                ("postal_code", "-"),
                ("country", "FIN"),
                (
                    "coordinates",
                    OrderedDict(
                        [("latitude", "60.000000"), ("longitude", "30.000000")]
                    ),
                ),
                ("evse_uid", "HELSINKI-1"),
                ("evse_id", "FI*TSL*EHELSINKI1"),
                ("connector_id", "3050"),
                ("connector_standard", "TESLA_S"),
                ("connector_format", "CABLE"),
                ("connector_power_type", "DC"),
            ]
        ),
        "cdr_token": OrderedDict(
            [
                ("uid", "APP-TOKEN"),
                ("type", "APP_USER"),
                ("contract_id", "DE8ACC12E46L89"),
            ]
        ),
        "country_code": "FI",
        "credit": False,
        "currency": "EUR",
        "end_date_time": "2022-05-19T18:12:56Z",
        "id": "6d6cba99cd8a425fae8a8cd0cd4c2a7a",
        "last_updated": "2022-05-19T18:12:56Z",
        "party_id": "CPO",
        "session_id": "test-transactions",
        "start_date_time": "2022-05-19T18:12:55Z",
        "tariffs": [
            OrderedDict(
                [
                    ("id", "EKI1"),
                    (
                        "elements",
                        [
                            OrderedDict(
                                [
                                    (
                                        "price_components",
                                        [
                                            OrderedDict(
                                                [
                                                    ("type", "ENERGY"),
                                                    ("price", 0.5),
                                                    ("vat", 24.0),
                                                    ("step_size", 0),
                                                ]
                                            )
                                        ],
                                    )
                                ]
                            )
                        ],
                    ),
                    (
                        "tariff_alt_text",
                        [OrderedDict([("language", "EN"), ("text", "0,50€/kWh")])],
                    ),
                    ("country_code", "FI"),
                    ("party_id", "000"),
                    ("currency", "EUR"),
                ]
            )
        ],
        "total_cost": OrderedDict([("excl_vat", 5), ("incl_vat", 6.2)]),
        "total_energy": 10.0,
        "total_time": 0.0,
    }


class AuthorizeData:
    accept_authorization = {
        "status_code": 1000,
        "status_message": "Success",
        "timestamp": "2022-11-07T06:41:41Z",
        "data": {
            "allowed": "ALLOWED",
            "token": {
                "country_code": "FI",
                "party_id": "MSP",
                "uid": "EKI1",
                "type": "RFID",
                "contract_id": "CONTRACT-EKI",
                "visual_number": "123456",
                "issuer": "EKI",
                "valid": True,
                "whitelist": "NEVER",
                "language": "FI",
            },
            "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        },
    }

    accept_authorization_msp = dict(result="ALLOWED")


class TokenAuthorizationData:
    authorization_webhook_calls = [
        dict(
            url="https://chargerhub.proxy.beeceptor.com/local-msp/webhooks/authorize/EKI1/",
            json={"token_id": "EKI1", "location_id": None},
            headers={"content-type": "application/json", "accept": "application/json"},
            verify=False,
            timeout=28,
        )
    ]

    invalid_token = {
        "data": {
            "allowed": "EXPIRED",
            "authorization_reference": "",
            "token": {
                "country_code": "FI",
                "party_id": "MSP",
                "uid": "EKI1",
                "type": "APP_USER",
                "contract_id": "CONTRACT_F",
                "visual_number": "123C",
                "issuer": "eki",
                "valid": False,
                "whitelist": "NEVER",
                "last_updated": "2022-01-10T07:00:01Z",
            },
        },
        "status_code": 1000,
        "status_message": "Your charging token is not valid at the moment",
        "timestamp": "2022-01-01T12:00:00Z",
    }
    webhook_data = [  # This is the data that is sent to the webhook
        {
            "url": "https://chargerhub.proxy.beeceptor.com/local-msp/webhooks/authorize/EKI1/",
            "json": {"token_id": "EKI1", "location_id": "HELSINKI-1"},
            "headers": {
                "content-type": "application/json",
                "accept": "application/json",
            },
            "verify": False,
            "timeout": 28,
        }
    ]
    location_not_found = {
        "data": {
            "allowed": "NOT_ALLOWED",
            "authorization_reference": "",
            "token": {
                "country_code": "FI",
                "party_id": "MSP",
                "uid": "EKI1",
                "type": "APP_USER",
                "contract_id": "CONTRACT_F",
                "visual_number": "123C",
                "issuer": "eki",
                "valid": True,
                "whitelist": "NEVER",
                "last_updated": "2022-01-10T07:00:01Z",
            },
        },
        "status_code": 1000,
        "status_message": "Your charging token is not allowed to charge at this "
        "location",
        "timestamp": "2022-01-01T12:00:00Z",
    }

    location_not_found2 = {
        "data": {
            "allowed": "NOT_ALLOWED",
            "authorization_reference": "",
            "token": {
                "country_code": "FI",
                "party_id": "MSP",
                "uid": "EKI1",
                "type": "APP_USER",
                "contract_id": "CONTRACT_F",
                "visual_number": "123C",
                "issuer": "eki",
                "valid": True,
                "whitelist": "NEVER",
                "last_updated": "2022-01-10T07:00:01Z",
            },
        },
        "status_code": 1000,
        "status_message": "Your charging token is not allowed to charge (at this "
        "location)",
        "timestamp": "2022-01-01T12:00:00Z",
    }

    non_existent_token = {
        "data": "",
        "status_code": 2004,
        "status_message": "***",  # Ignore the text, it's not specified in OCPI specs
        "timestamp": "2022-01-01T12:00:00Z",
    }

    authorization_object_data = {
        "_state": "***",  # Anything goes
        "authorization_reference": "FI*MSP*A*MOCK-1",
        "created": datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc),
        "id": "***",
        "max_price": Decimal("30.00"),
        "session_id": None,
        "token_uid": None,
        "updated": datetime(2022, 1, 1, 12, 0, tzinfo=pytz.utc),
    }

    success = {
        "data": {
            "allowed": "ALLOWED",
            "authorization_reference": "FI*MSP*A*MOCK-1",  # "MOCK-1" comes from uuid4 through a mysterious process
            "token": {
                "country_code": "FI",
                "party_id": "MSP",
                "uid": "EKI1",
                "type": "APP_USER",
                "contract_id": "CONTRACT_F",
                "visual_number": "123C",
                "issuer": "eki",
                "valid": True,
                "whitelist": "NEVER",
                "last_updated": "2022-01-10T07:00:01Z",
            },
        },
        "status_code": 1000,
        "status_message": "Success",
        "timestamp": "2022-01-01T12:00:00Z",
    }


class StopTransactionResponses:
    stop1 = {
        "charge_detail_record": {
            "detail_url": "http://testserver.test:8000/ocpi/2.2.1/cdrs/FI/CPO/FI*CPO*C*MOCK-1",
            "auth_method": "AUTH_REQUEST",
            "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
            "cdr_location": dict(
                [
                    ("id", "HELSINKI-1"),
                    ("address", "Helsinki 12"),
                    ("name", "Helsinki " "Supercharger"),
                    ("city", "Helsinki"),
                    ("postal_code", "-"),
                    ("country", "FIN"),
                    (
                        "coordinates",
                        dict([("latitude", "60.000000"), ("longitude", "30.000000")]),
                    ),
                    ("evse_uid", "HELSINKI-3"),
                    ("evse_id", "FI*TSL*EHELSINKI3"),
                    ("connector_id", "1"),
                    ("connector_standard", "TESLA_S"),
                    ("connector_format", "CABLE"),
                    ("connector_power_type", "DC"),
                ]
            ),
            "cdr_token": dict(
                [("uid", "EKI1"), ("type", "RFID"), ("contract_id", "DE8ACC12E46L89")]
            ),
            "country_code": "FI",
            "credit": False,
            "currency": "EUR",
            "end_date_time": "2022-01-01T13:00:00Z",
            "id": "FI*CPO*C*MOCK-1",
            "last_updated": "2022-01-01T13:30:00Z",
            "party_id": "CPO",
            "session_id": "FI*CPO*S*MOCK-1",
            "start_date_time": "2022-01-01T12:00:00Z",
            "tariffs": [
                dict(
                    [
                        (
                            "detail_url",
                            "http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/CPO/EKI1",
                        ),
                        ("id", "EKI1"),
                        (
                            "elements",
                            [
                                dict(
                                    [
                                        (
                                            "price_components",
                                            [
                                                dict(
                                                    [
                                                        ("type", "ENERGY"),
                                                        ("price", 0.5),
                                                        ("vat", 24.0),
                                                        ("step_size", 0),
                                                    ]
                                                )
                                            ],
                                        )
                                    ]
                                )
                            ],
                        ),
                        (
                            "tariff_alt_text",
                            [dict([("language", "EN"), ("text", "0,50€/kWh")])],
                        ),
                        ("country_code", "FI"),
                        ("party_id", "CPO"),
                        ("last_updated", "2022-01-01T13:30:00Z"),
                        ("currency", "EUR"),
                    ]
                )
            ],
            "total_cost": dict([("excl_vat", 17.5), ("incl_vat", 21.7)]),
            "total_energy": 35.0,
            "total_time": 1.000,
        },
        "kwh_total": Decimal("35.000"),
        "session": {
            "detail_url": "http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1",
            "auth_method": "AUTH_REQUEST",
            "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
            "billed_to": "FI*MSP",
            "connector_id": "1",
            "currency": "EUR",
            "end_date_time": "2022-01-01T13:00:00Z",
            "evse_uid": "HELSINKI-3",
            "location_id": "HELSINKI-1",
            "session_id": "FI*CPO*S*MOCK-1",
            "start_date_time": "2022-01-01T12:00:00Z",
            "start_kwh": 120.0,
            "stop_kwh": 155.0,
            "status": "COMPLETED",
            "token": dict(
                [
                    ("token_id", "EKI1"),
                    ("type", "RFID"),
                    ("contract_id", "DE8ACC12E46L89"),
                ]
            ),
            "total_cost_excl_vat": 17.5,
            "total_cost_incl_vat": 21.7,
            "last_updated": "2022-01-01T13:30:00Z",
        },
        "session_id": "FI*CPO*S*MOCK-1",
        "status_text": "Session finished",
    }

    stop2 = {
        "charge_detail_record": {
            "auth_method": "COMMAND",
            "authorization_reference": "FI*001-AUTH-REFERENCE",
            "cdr_location": OrderedDict(
                [
                    ("id", "HELSINKI-1"),
                    ("address", "Helsinki 12"),
                    ("name", "Helsinki " "Supercharger"),
                    ("city", "Helsinki"),
                    ("postal_code", "-"),
                    ("country", "FIN"),
                    (
                        "coordinates",
                        OrderedDict(
                            [("latitude", "60.000000"), ("longitude", "30.000000")]
                        ),
                    ),
                    ("evse_uid", "HELSINKI-3"),
                    ("evse_id", "FI*TSL*EHELSINKI3"),
                    ("connector_id", "1"),
                    ("connector_standard", "TESLA_S"),
                    ("connector_format", "CABLE"),
                    ("connector_power_type", "DC"),
                ]
            ),
            "cdr_token": OrderedDict(
                [
                    ("uid", "SOME-ADHOC-TOKEN"),
                    ("type", "AD_HOC_USER"),
                    ("contract_id", "INTERNAL"),
                ]
            ),
            "country_code": "FI",
            "credit": False,
            "currency": "EUR",
            "end_date_time": "2022-01-01T12:00:00Z",
            "id": "FI*CPO*C*MOCK-2",
            "last_updated": "2022-01-01T12:00:00Z",
            "party_id": "CPO",
            "session_id": "FI*CPO*S*MOCK-1",
            "start_date_time": "2022-01-01T12:00:00Z",
            "tariffs": [
                OrderedDict(
                    [
                        ("id", "EKI1"),
                        (
                            "elements",
                            [
                                OrderedDict(
                                    [
                                        (
                                            "price_components",
                                            [
                                                OrderedDict(
                                                    [
                                                        ("type", "ENERGY"),
                                                        ("price", 0.5),
                                                        ("vat", 24.0),
                                                        ("step_size", 0),
                                                    ]
                                                )
                                            ],
                                        )
                                    ]
                                )
                            ],
                        ),
                        (
                            "tariff_alt_text",
                            [OrderedDict([("language", "EN"), ("text", "0,50€/kWh")])],
                        ),
                        ("country_code", "FI"),
                        ("party_id", "000"),
                        ("currency", "EUR"),
                    ]
                )
            ],
            "total_cost": OrderedDict([("excl_vat", 61.73), ("incl_vat", 76.54)]),
            "total_energy": 123.45,
            "total_time": 0.0,
        },
        "kwh_total": Decimal("123.450"),
        "session": {
            "auth_method": "COMMAND",
            "authorization_reference": "FI*001-AUTH-REFERENCE",
            "billed_to": "FI*EON",
            "connector_id": "1",
            "currency": "EUR",
            "end_date_time": "2022-01-01T12:00:00Z",
            "evse_uid": "HELSINKI-3",
            "location_id": "HELSINKI-1",
            "session_id": "FI*CPO*S*MOCK-1",
            "start_date_time": "2022-01-01T12:00:00Z",
            "start_kwh": 0.0,
            "status": "COMPLETED",
            "token": OrderedDict(
                [
                    ("token_id", "SOME-ADHOC-TOKEN"),
                    ("type", "AD_HOC_USER"),
                    ("contract_id", "INTERNAL"),
                ]
            ),
            "total_cost_excl_vat": 61.73,
            "total_cost_incl_vat": 76.54,
        },
        "session_id": "FI*CPO*S*MOCK-1",
        "status_text": "Session finished",
    }

    stop3 = OrderedDict(
        [
            (
                "charge_detail_record",
                OrderedDict(
                    [
                        ("auth_method", "COMMAND"),
                        ("authorization_reference", "FI*MSP-AUTH-REFERENCE"),
                        (
                            "cdr_location",
                            OrderedDict(
                                [
                                    ("address", "Helsinki 12"),
                                    ("city", "Helsinki"),
                                    ("connector_format", "CABLE"),
                                    ("connector_id", "1"),
                                    ("connector_power_type", "DC"),
                                    ("connector_standard", "TESLA_S"),
                                    (
                                        "coordinates",
                                        OrderedDict(
                                            [
                                                ("latitude", "60.000000"),
                                                ("longitude", "30.000000"),
                                            ]
                                        ),
                                    ),
                                    ("country", "FIN"),
                                    ("evse_id", "FI*TSL*EHELSINKI3"),
                                    ("evse_uid", "HELSINKI-3"),
                                    ("id", "HELSINKI-1"),
                                    ("name", "Helsinki Supercharger"),
                                    ("postal_code", "-"),
                                ]
                            ),
                        ),
                        (
                            "cdr_token",
                            OrderedDict(
                                [
                                    ("contract_id", "INTERNAL"),
                                    ("type", "AD_HOC_USER"),
                                    ("uid", "SOME-ADHOC-TOKEN"),
                                ]
                            ),
                        ),
                        ("country_code", "FI"),
                        ("credit", False),
                        ("currency", "EUR"),
                        (
                            "detail_url",
                            "http://testserver.test:8000/ocpi/2.2.1/cdrs/FI/CPO/FI*CPO*C*MOCK-2",
                        ),
                        ("end_date_time", "2022-01-01T12:23:00Z"),
                        ("id", "FI*CPO*C*MOCK-2"),
                        ("last_updated", "2022-01-01T12:23:00Z"),
                        ("party_id", "CPO"),
                        ("session_id", "FI*CPO*S*MOCK-1"),
                        ("start_date_time", "2022-01-01T12:00:00Z"),
                        (
                            "tariffs",
                            [
                                OrderedDict(
                                    [
                                        (
                                            "detail_url",
                                            "http://testserver.test:8000/ocpi/2.2.1/tariffs/FI/CPO/EKI1",
                                        ),
                                        ("id", "EKI1"),
                                        (
                                            "elements",
                                            [
                                                OrderedDict(
                                                    [
                                                        (
                                                            "price_components",
                                                            [
                                                                OrderedDict(
                                                                    [
                                                                        (
                                                                            "type",
                                                                            "ENERGY",
                                                                        ),
                                                                        ("price", 0.5),
                                                                        ("vat", 24.0),
                                                                        (
                                                                            "step_size",
                                                                            0,
                                                                        ),
                                                                    ]
                                                                )
                                                            ],
                                                        )
                                                    ]
                                                )
                                            ],
                                        ),
                                        (
                                            "tariff_alt_text",
                                            [
                                                OrderedDict(
                                                    [
                                                        ("language", "EN"),
                                                        ("text", "0,50€/kWh"),
                                                    ]
                                                )
                                            ],
                                        ),
                                        ("country_code", "FI"),
                                        ("party_id", "CPO"),
                                        ("last_updated", "2022-01-01T12:23:00Z"),
                                        ("currency", "EUR"),
                                    ]
                                )
                            ],
                        ),
                        (
                            "total_cost",
                            OrderedDict([("excl_vat", 61.73), ("incl_vat", 76.54)]),
                        ),
                        ("total_energy", 123.45),
                        ("total_time", 0.383),
                    ]
                ),
            ),
            ("kwh_total", Decimal("123.450")),
            (
                "session",
                OrderedDict(
                    [
                        ("auth_method", "COMMAND"),
                        ("authorization_reference", "FI*MSP-AUTH-REFERENCE"),
                        ("billed_to", "FI*MSP"),
                        ("connector_id", "1"),
                        ("currency", "EUR"),
                        (
                            "detail_url",
                            "http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1",
                        ),
                        ("end_date_time", "2022-01-01T12:23:00Z"),
                        ("evse_uid", "HELSINKI-3"),
                        ("last_updated", "2022-01-01T12:23:00Z"),
                        ("location_id", "HELSINKI-1"),
                        ("session_id", "FI*CPO*S*MOCK-1"),
                        ("start_date_time", "2022-01-01T12:00:00Z"),
                        ("start_kwh", 0.0),
                        ("status", "COMPLETED"),
                        ("stop_kwh", 123.45),
                        (
                            "token",
                            OrderedDict(
                                [
                                    ("contract_id", "INTERNAL"),
                                    ("token_id", "SOME-ADHOC-TOKEN"),
                                    ("type", "AD_HOC_USER"),
                                ]
                            ),
                        ),
                        ("total_cost_excl_vat", 61.73),
                        ("total_cost_incl_vat", 76.54),
                    ]
                ),
            ),
            ("session_id", "FI*CPO*S*MOCK-1"),
            ("status_text", "Session finished"),
        ]
    )


class SessionData:
    wrong_evse = {
        "status": "ACTIVE",
        "auth_method": "WHITELIST",
        "country_code": "FI",
        "party_id": "CPO",
        "currency": "PHP",
        "id": "123",
        "cdr_token": {
            "country_code": "FI",
            "party_id": "MSP",
            "contract_id": "789",
            "type": "APP_USER",
            "uid": "456",
        },
        "location_id": "12",
        "evse_uid": {"evse_uid": "87da"},
        "start_date_time": "2022-01-01T12:00:00Z",
    }

    meter_values_1 = {  # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1',
        "auth_method": "COMMAND",
        "authorization_reference": "FI*MSP-AUTH-REFERENCE",
        "cdr_token": OrderedDict(
            [
                ("country_code", "FI"),
                ("party_id", "MSP"),
                ("uid", "SOME-ADHOC-TOKEN"),
                ("type", "AD_HOC_USER"),
                ("contract_id", "INTERNAL"),
            ]
        ),
        "charging_periods": [
            OrderedDict(
                [
                    ("start_date_time", "2022-01-01T12:00:00Z"),
                    ("tariff", "EKI1"),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "123.4500")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "42.0000")]
                            ),
                            OrderedDict([("type", "POWER"), ("volume", "150.0000")]),
                        ],
                    ),
                ]
            )
        ],
        "connector_id": "1",
        "country_code": "FI",
        "currency": "EUR",
        "evse_uid": "HELSINKI-3",
        "kwh": 123.45,
        "location_id": "HELSINKI-1",
        "party_id": "CPO",
        "start_date_time": "2022-01-01T12:00:00Z",
        "last_updated": "2022-01-01T12:00:00Z",
        "status": "ACTIVE",
        "total_cost": OrderedDict([("excl_vat", 61.73), ("incl_vat", 76.54)]),
        "id": "FI*CPO*S*MOCK-1",
    }

    meter_values_1_webhook = {
        "auth_method": "COMMAND",
        "country_code": "FI",
        "party_id": "CPO",
        "uid": "FI*CPO*S*MOCK-1",
        "start_date_time": "2022-01-01T12:00:00Z",
        "kwh": 123.45,
        "charging_periods": [
            {
                "start_date_time": "2022-01-01T12:00:00Z",
                "tariff": "EKI1",
                "dimensions": [
                    {"type": "ENERGY", "volume": "123.4500"},
                    {"type": "STATE_OF_CHARGE", "volume": "42.0000"},
                    {"type": "POWER", "volume": "150.0000"},
                ],
            }
        ],
        "total_time": "0.00",
        "display_total_time": "0 s",
        "cdr_token": OrderedDict(
            [
                ("country_code", "FI"),
                ("party_id", "MSP"),
                ("uid", "SOME-ADHOC-TOKEN"),
                ("type", "AD_HOC_USER"),
                ("contract_id", "INTERNAL"),
            ]
        ),
        "authorization_reference": "FI*MSP-AUTH-REFERENCE",
        "location_id": "HELSINKI-1",
        "evse_uid": "HELSINKI-3",
        "connector_id": "1",
        "currency": "EUR",
        "total_cost": OrderedDict([("excl_vat", 61.73), ("incl_vat", 76.54)]),
        "status": "ACTIVE",
        "display_status": "Active",
        "last_updated": "2022-01-01T12:00:00Z",
    }

    stop4 = {  # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1',
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "cdr_token": OrderedDict(
            [("uid", "EKI1"), ("type", "RFID"), ("contract_id", "DE8ACC12E46L89")]
        ),
        "charging_periods": [
            OrderedDict(
                [
                    ("start_date_time", "2022-01-01T12:00:00Z"),
                    ("tariff", "EKI1"),
                    (
                        "dimensions",
                        [
                            OrderedDict([("type", "ENERGY"), ("volume", "35.0000")]),
                            OrderedDict(
                                [("type", "STATE_OF_CHARGE"), ("volume", "80.0000")]
                            ),
                            OrderedDict([("type", "TIME"), ("volume", "1.0000")]),
                        ],
                    ),
                ]
            )
        ],
        "connector_id": "1",
        "country_code": "FI",
        "currency": "EUR",
        "end_date_time": "2022-01-01T13:00:00Z",
        "evse_uid": "HELSINKI-3",
        "kwh": 35.0,
        "location_id": "HELSINKI-1",
        "party_id": "CPO",
        "start_date_time": "2022-01-01T12:00:00Z",
        "status": "COMPLETED",
        "total_cost": OrderedDict([("excl_vat", 17.5), ("incl_vat", 21.7)]),
        "id": "FI*CPO*S*MOCK-1",
        "last_updated": "2022-01-01T13:30:00Z",
    }


class RfidTestData:
    expected_data_1 = {  # 'detail_url': 'http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1',
        "auth_method": "AUTH_REQUEST",
        "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
        "cdr_token": dict(
            [("uid", "EKI1"), ("type", "RFID"), ("contract_id", "DE8ACC12E46L89")]
        ),
        "connector_id": "1",
        "country_code": "FI",
        "currency": "EUR",
        "evse_uid": "HELSINKI-3",
        "kwh": 0.0,
        "location_id": "HELSINKI-1",
        "party_id": "CPO",
        "start_date_time": "2022-01-01T12:00:00Z",
        "status": "ACTIVE",
        "last_updated": "2022-01-01T12:00:00Z",
        "id": "FI*CPO*S*MOCK-1",
    }

    expected_response_1 = {
        "session": {
            "detail_url": "http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1",
            "auth_method": "AUTH_REQUEST",
            "authorization_reference": "MOCK-AUTHORIZATION-REFERENCE",
            "billed_to": "FI*MSP",
            "connector_id": "1",
            "currency": "EUR",
            "evse_uid": "HELSINKI-3",
            "location_id": "HELSINKI-1",
            "session_id": "FI*CPO*S*MOCK-1",
            "start_date_time": "2022-01-01T12:00:00Z",
            "start_kwh": 120.0,
            "stop_kwh": 120.0,
            "status": "ACTIVE",
            "last_updated": "2022-01-01T12:00:00Z",
            "token": OrderedDict(
                [
                    ("token_id", "EKI1"),
                    ("type", "RFID"),
                    ("contract_id", "DE8ACC12E46L89"),
                ]
            ),
        },
        "status_text": "Session started",
    }


class SessionCommandsData:
    evse_inoperative_response = {
        "data": {
            "result": "REJECTED",
            "timeout": 60,
            "message": [
                {"language": "EN", "text": "The charger is inoperative"},
                {"language": "NL", "text": "De oplader werkt niet"},
                {"language": "FR", "text": "Le chargeur ne fonctionne pas"},
                {"language": "DE", "text": "Das Ladegerät funktioniert nicht"},
                {"language": "ES", "text": "El cargador no funciona"},
                {"language": "IT", "text": "Il caricatore non è operativo"},
                {"language": "PT", "text": "O carregador está inoperante"},
                {"language": "LB", "text": "De Ladegerät ass net funktionnéiert"},
                {"language": "CY", "text": "Mae'r charger yn anweithredol"},
                {"language": "GA", "text": "Tá an charger neamhoibríoch"},
                {"language": "BE", "text": "Зарадная прылада не працуе"},
                {"language": "BG", "text": "Зарядното устройство не работи"},
                {"language": "RO", "text": "Încărcătorul nu funcționează"},
                {"language": "BS", "text": "Punjač nije u funkciji"},
                {"language": "MK", "text": "Полначот не работи"},
                {"language": "SQ", "text": "Karikuesi nuk funksionon"},
                {"language": "SR", "text": "Пуњач не ради"},
                {"language": "TR", "text": "şarj cihazı çalışmıyor"},
                {"language": "UK", "text": "Зарядний пристрій не працює"},
                {"language": "EL", "text": "Ο φορτιστής δεν λειτουργεί"},
                {"language": "PL", "text": "Ładowarka nie działa"},
                {"language": "HU", "text": "A töltő nem működik"},
                {"language": "CS", "text": "Nabíječka je nefunkční"},
                {"language": "SK", "text": "Nabíjačka je nefunkčná"},
                {"language": "SL", "text": "Polnilnik ne deluje"},
                {"language": "FI", "text": "Laturi on epäkunnossa"},
                {"language": "NN", "text": "Laderen er ute av drift"},
                {"language": "DA", "text": "Opladeren er ude af drift"},
                {"language": "SV", "text": "Laddaren fungerar inte"},
                {"language": "IS", "text": "Hleðslutækið er óvirkt"},
                {"language": "ET", "text": "Laadija ei tööta"},
                {"language": "LT", "text": "Įkroviklis neveikia"},
                {"language": "LV", "text": "Lādētājs nedarbojas"},
                {"language": "AF", "text": "Die laaier werk nie"},
            ],
        },
        "status_code": 2000,
        "status_message": "",
        "timestamp": "2022-01-01T12:00:00Z",
    }

    authorization_success = {
        "allowed": "ALLOWED",
        "auth_method": "COMMAND",
        "authorization_reference": "FI*MSP-AUTH-REFERENCE",
        "billed_to": "FI*MSP",
        "info": [
            {"language": "EN", "text": "The token is accepted"},
            {"language": "NL", "text": "Het token wordt geaccepteerd"},
            {"language": "FR", "text": "Le jeton est accepté"},
            {"language": "DE", "text": "Der Token wird akzeptiert"},
            {"language": "ES", "text": "Se acepta la ficha"},
            {"language": "IT", "text": "Il token è accettato"},
            {"language": "PT", "text": "O token é aceito"},
            {"language": "LB", "text": "Den Token gëtt ugeholl"},
            {"language": "CY", "text": "Derbynnir y tocyn"},
            {"language": "GA", "text": "Glactar leis an comhartha"},
            {"language": "BE", "text": "Токен прыняты"},
            {"language": "BG", "text": "Токенът е приет"},
            {"language": "RO", "text": "Jetonul este acceptat"},
            {"language": "BS", "text": "Token je prihvaćen"},
            {"language": "MK", "text": "Токенот е прифатен"},
            {"language": "SQ", "text": "Shenja pranohet"},
            {"language": "SR", "text": "Токен је прихваћен"},
            {"language": "TR", "text": "Jeton kabul ediliyor"},
            {"language": "UK", "text": "Токен прийнято"},
            {"language": "EL", "text": "Το διακριτικό γίνεται αποδεκτό"},
            {"language": "PL", "text": "Token jest akceptowany"},
            {"language": "HU", "text": "A tokent elfogadják"},
            {"language": "CS", "text": "Token je přijat"},
            {"language": "SK", "text": "Token je akceptovaný"},
            {"language": "SL", "text": "Žeton je sprejet"},
            {"language": "FI", "text": "Lataustunniste on hyväksytty"},
            {"language": "NN", "text": "Tokenet er akseptert"},
            {"language": "DA", "text": "Tokenet accepteres"},
            {"language": "SV", "text": "Token accepteras"},
            {"language": "IS", "text": "Táknið er samþykkt"},
            {"language": "ET", "text": "Token on vastu võetud"},
            {"language": "LT", "text": "Žetonas priimtas"},
            {"language": "LV", "text": "Žetons ir pieņemts"},
            {"language": "AF", "text": "Die teken word aanvaar"},
        ],
        "location": {},
        "responding_party": "FI*CPO",
        "status_text": "The token is accepted",
        "token": {
            "billed_to": "FI*MSP (EMSP)",  # This is actually a CredentialsRole, we just cast it to str
            "type": "AD_HOC_USER",
            "uid": "SOME-ADHOC-TOKEN",
            "valid": True,
        },
    }
    start_webhook = {
        "auth": ("john", "his-password"),
        "headers": {"content-type": "application/json", "accept": "application/json"},
        "json": {
            "auth_method": "COMMAND",
            "authorization_reference": "e86baa82cee14ac5bfd00b85371aa798",
            "from_party": "FI*MSP",
            "billed_to": "FI*MSP",
            "connector_id": None,
            "evse_id": "HELSINKI-3",
            "response_url": "http://testserver.test:8000/api/cpo/v2/chargepoint/remote_command_result.e86baa82cee14ac5bfd00b85371aa798",
            "token_id": "FI*001*T*ADMIN*TOKEN",
            "token_type": "OTHER",
        },
        "timeout": 10,
        "url": "http://fakehost/start/HELSINKI-3/",
        "verify": False,
    }

    stop_success = {
        "data": {
            "result": "ACCEPTED",
            "timeout": 60,
            "message": [
                {"language": "EN", "text": "Stopping charging session"},
                {"language": "NL", "text": "Oplaadsessie stoppen"},
                {"language": "FR", "text": "Arrêt de la session de charge"},
                {"language": "DE", "text": "Beenden der Ladesitzung"},
                {"language": "ES", "text": "Deteniendo la sesión de carga"},
                {"language": "IT", "text": "Interruzione della sessione di ricarica"},
                {"language": "PT", "text": "Parando a sessão de carregamento"},
                {"language": "LB", "text": "Opluedsession stoppen"},
                {"language": "CY", "text": "Rhoi'r gorau i sesiwn codi tâl"},
                {"language": "GA", "text": "Seisiún luchtaithe a stopadh"},
                {"language": "BE", "text": "Спыненне сеансу зарадкі"},
                {"language": "BG", "text": "Спиране на сесията на зареждане"},
                {"language": "RO", "text": "Oprirea sesiunii de încărcare"},
                {"language": "BS", "text": "Zaustavljanje sesije punjenja"},
                {"language": "MK", "text": "Запирање на сесијата за полнење"},
                {"language": "SQ", "text": "Ndalimi i seancës së karikimit"},
                {"language": "SR", "text": "Заустављање сесије пуњења"},
                {"language": "TR", "text": "Şarj oturumunu durdurma"},
                {"language": "UK", "text": "Припинення сеансу зарядки"},
                {"language": "EL", "text": "Διακοπή περιόδου λειτουργίας φόρτισης"},
                {"language": "PL", "text": "Zatrzymywanie sesji ładowania"},
                {"language": "HU", "text": "A töltési munkamenet leállítása"},
                {"language": "CS", "text": "Zastavení nabíjecí relace"},
                {"language": "SK", "text": "Zastavuje sa relácia nabíjania"},
                {"language": "SL", "text": "Ustavitev seje polnjenja"},
                {"language": "FI", "text": "Latausistuntoa lopetellaan"},
                {"language": "NN", "text": "Stopper ladeøkten"},
                {"language": "DA", "text": "Stopper opladningssession"},
                {"language": "SV", "text": "Stoppar laddningssessionen"},
                {"language": "IS", "text": "Stöðvar hleðslulotu"},
                {"language": "ET", "text": "Laadimisseansi peatamine"},
                {"language": "LT", "text": "Sustabdoma įkrovimo sesija"},
                {"language": "LV", "text": "Uzlādes sesijas pārtraukšana"},
                {"language": "AF", "text": "Stop laaisessie"},
            ],
        },
        "status_code": 1000,
        "status_message": "Success",
        "timestamp": "2022-01-01T12:00:00Z",
    }

    stop_webhook = {
        "auth": ("john", "his-password"),
        "headers": {"content-type": "application/json", "accept": "application/json"},
        "json": {
            "response_url": "http://testserver.test:8000/api/cpo/v2/chargepoint/remote_command_result/COMMAND_ID/",
            "token_id": "FI*001*T*ADMIN*TOKEN",
            "token_type": "OTHER",
            "authorization_reference": "e86baa82cee14ac5bfd00b85371aa798",
            "auth_method": "COMMAND",
            "from_party": "FI*MSP",
            "evse_id": "HELSINKI-3",
            "connector_id": "1",
            "billed_to": "FI*MSP",
        },
        "timeout": 10,
        "url": "http://fakehost/stop/HELSINKI-3/",
        "verify": False,
    }


class AppChargingData:
    expected_data_sent_max_price = {
        "headers": {
            "Authorization": "Token YWRiYjA3ZjYzNGE3OTFmNTI5ZWMzODg3NzRjZDI0YzhlMWViODA0M2RiYjAwOGU5MzBlZTdlMWVkZWI1YTBiOA==",
            "OCPI-from-country-code": "FI",
            "OCPI-from-party-id": "MSP",
            "OCPI-to-country-code": "FI",
            "OCPI-to-party-id": "CPO",
            "platform-revision": "REVISION",
            "accept": "application/json",
            "content-type": "application/json",
        },
        "json": {
            "authorization_reference": "REFERENCE-123",
            # 'connector_id': '1',  # OCPI 2.2 doesn't support this in the remote start command
            "evse_uid": "HELSINKI-3",
            "location_id": "HELSINKI-1",
            "response_url": "http://testserver.test:8000/ocpi/2.2.1/commands/COMMAND_RESULT/start/REFERENCE-123",
            "token": OrderedDict(
                [
                    ("country_code", "FI"),
                    ("party_id", "MSP"),
                    ("uid", "FI*MSP*T*APP*MOCK-1"),
                    ("type", "APP_USER"),
                    ("contract_id", "CONTRACT-123"),
                ]
            ),
        },
        "timeout": 25,
    }

    expected_data_sent = {
        "headers": {
            "Authorization": "Token YWRiYjA3ZjYzNGE3OTFmNTI5ZWMzODg3NzRjZDI0YzhlMWViODA0M2RiYjAwOGU5MzBlZTdlMWVkZWI1YTBiOA==",
            "OCPI-from-country-code": "FI",
            "OCPI-from-party-id": "MSP",
            "OCPI-to-country-code": "FI",
            "OCPI-to-party-id": "CPO",
            "content-type": "application/json",
            "accept": "application/json",
            "platform-revision": "REVISION",
        },
        "json": {
            "authorization_reference": "REFERENCE-123",
            "evse_uid": "HELSINKI-3",
            "location_id": "HELSINKI-1",
            "response_url": "http://testserver.test:8000/ocpi/2.2.1/commands/COMMAND_RESULT/start/REFERENCE-123",
            "token": dict(
                [
                    ("country_code", "FI"),
                    ("party_id", "MSP"),
                    ("uid", "FI*MSP*T*APP*MOCK-1"),
                    ("type", "APP_USER"),
                    ("contract_id", "CONTRACT-123"),
                ]
            ),
        },
        "timeout": 25,
    }


class CpoApiData:
    expected_status_change_messages = [
        {
            "url": "http://localhost:8002/ocpi/2.2/locations/FI/CPO/HELSINKI-1/HELSINKI-3",
            "data": '{"status": "CHARGING", "last_updated": "2022-01-01 12:00:00+00:00"}',  # Note that these are str
            "headers": {
                "Authorization": "Token YWRiYjA3ZjYzNGE3OTFmNTI5ZWMzODg3NzRjZDI0YzhlMWViODA0M2RiYjAwOGU5MzBlZTdlMWVkZWI1YTBiOA==",
                "content-type": "application/json",
                "accept": "application/json",
                "platform-revision": "REVISION",
                "OCPI-to-country-code": "FI",
                "OCPI-to-party-id": "MSP",
                "OCPI-from-country-code": "FI",
                "OCPI-from-party-id": "CPO",
            },
        },
        {
            "url": "http://localhost:8001/ocpi/2.2/locations/FI/CPO/HELSINKI-1/HELSINKI-3",
            "data": '{"status": "CHARGING", "last_updated": "2022-01-01 12:00:00+00:00"}',
            "headers": {
                "Authorization": "Token QzMyNUQ2NTMyNzBCNzdBMzVDQkRFMzc5QjhFQTM5ODA3OTVCOTA5QUZGN0MyQUIxNEE3OURFQzExRTBENTU2RA==",
                "content-type": "application/json",
                "accept": "application/json",
                "platform-revision": "REVISION",
                "OCPI-to-country-code": "FI",
                "OCPI-to-party-id": "HB2",
                "OCPI-from-country-code": "FI",
                "OCPI-from-party-id": "CPO",
            },
        },
        {
            "url": "http://localhost:8002/ocpi/2.2/locations/FI/CPO/HELSINKI-1/HELSINKI-3",
            "data": '{"status": "CHARGING", "last_updated": "2022-01-01 12:00:00+00:00"}',
            "headers": {
                "Authorization": "Token YWRiYjA3ZjYzNGE3OTFmNTI5ZWMzODg3NzRjZDI0YzhlMWViODA0M2RiYjAwOGU5MzBlZTdlMWVkZWI1YTBiOA==",
                "content-type": "application/json",
                "accept": "application/json",
                "platform-revision": "REVISION",
                "OCPI-to-country-code": "FI",
                "OCPI-to-party-id": "001",
                "OCPI-from-country-code": "FI",
                "OCPI-from-party-id": "CPO",
            },
        },
    ]


class TariffData:
    expected_delete_calls = [
        {
            "args": (),
            "kwargs": {
                "headers": {
                    "Authorization": "Token "
                    "QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==",
                    "OCPI-from-country-code": "FI",
                    "OCPI-from-party-id": "CPO",
                    "OCPI-to-country-code": "FI",
                    "OCPI-to-party-id": "MSP",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "platform-revision": "REVISION",
                },
                "json": {},
                "url": "http://localhost:8001/ocpi/2.2.1/tariffs/FI/CPO/T1",
            },
        },
        {
            "args": (),
            "kwargs": {
                "headers": {
                    "Authorization": "Token "
                    "QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==",
                    "OCPI-from-country-code": "FI",
                    "OCPI-from-party-id": "CPO",
                    "OCPI-to-country-code": "FI",
                    "OCPI-to-party-id": "NAP",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "platform-revision": "REVISION",
                },
                "json": {},
                "url": "http://localhost:8001/ocpi/2.2.1/tariffs/FI/CPO/T1",
            },
        },
        {
            "args": (),
            "kwargs": {
                "headers": {
                    "Authorization": "Token "
                    "QUNCODIxNThFQzEzNkE5MkJFRUMwMDRFMzAxMEI4RDgyM0ZBOTVCOTYzNTU1OEYyRjgxNDBDOUVFODIxOUUzQw==",
                    "OCPI-from-country-code": "FI",
                    "OCPI-from-party-id": "CPO",
                    "OCPI-to-country-code": "FI",
                    "OCPI-to-party-id": "HUB",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "platform-revision": "REVISION",
                },
                "json": {},
                "url": "http://localhost:8001/ocpi/2.2.1/tariffs/FI/CPO/T1",
            },
        },
        {
            "args": (),
            "kwargs": {
                "headers": {
                    "Authorization": "Token "
                    "QzMyNUQ2NTMyNzBCNzdBMzVDQkRFMzc5QjhFQTM5ODA3OTVCOTA5QUZGN0MyQUIxNEE3OURFQzExRTBENTU2RA==",
                    "OCPI-from-country-code": "FI",
                    "OCPI-from-party-id": "CPO",
                    "OCPI-to-country-code": "FI",
                    "OCPI-to-party-id": "HB2",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "platform-revision": "REVISION",
                },
                "json": {},
                "url": "http://localhost:8001/ocpi/2.2/tariffs/FI/CPO/T1",
            },
        },
        {
            "args": (),
            "kwargs": {
                "headers": {
                    "Authorization": "Token "
                    "YWRiYjA3ZjYzNGE3OTFmNTI5ZWMzODg3NzRjZDI0YzhlMWViODA0M2RiYjAwOGU5MzBlZTdlMWVkZWI1YTBiOA==",
                    "OCPI-from-country-code": "FI",
                    "OCPI-from-party-id": "CPO",
                    "OCPI-to-country-code": "FI",
                    "OCPI-to-party-id": "001",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "platform-revision": "REVISION",
                },
                "json": {},
                "url": "http://localhost:8002/ocpi/2.2/tariffs/FI/CPO/T1",
            },
        },
    ]


class AdhocTokenData:
    start_session_method_calls = [
        {
            "auth": ("john", "his-password"),
            "headers": {
                "accept": "application/json",
                "content-type": "application/json",
            },
            "json": {
                "response_url": "http://testserver.test:8000/api/cpo/v2/chargepoint/remote_command_result/FI*MSP-AUTH-REFERENCE/",
                "token_id": "SOME-ADHOC-TOKEN",
                "token_type": "AD_HOC_USER",
                "authorization_reference": "FI*MSP-AUTH-REFERENCE",
                "auth_method": "COMMAND",
                "from_party": "FI*MSP",
                "evse_id": "HELSINKI-3",
                "connector_id": None,
                "billed_to": "FI*MSP",
            },
            "timeout": 10,
            "url": "http://fakehost/start/HELSINKI-3/",
            "verify": False,
        }
    ]

    start_transaction_response = {
        "session": {
            "detail_url": "http://testserver.test:8000/ocpi/2.2.1/sessions/FI/CPO/FI*CPO*S*MOCK-1",
            "auth_method": "COMMAND",
            "authorization_reference": "FI*MSP-AUTH-REFERENCE",
            "billed_to": "FI*MSP",
            "currency": "EUR",
            "evse_uid": "HELSINKI-3",
            "location_id": "HELSINKI-1",
            "connector_id": "1",
            "session_id": "FI*CPO*S*MOCK-1",
            "start_date_time": "2022-01-01T12:00:00Z",
            "start_kwh": 0.0,
            "stop_kwh": 0.0,
            "status": "ACTIVE",
            "last_updated": "2022-01-01T12:00:00Z",
            "token": OrderedDict(
                [
                    ("token_id", "SOME-ADHOC-TOKEN"),
                    ("type", "AD_HOC_USER"),
                    ("contract_id", "INTERNAL"),
                ]
            ),
        },
        "status_text": "Session started",
    }
