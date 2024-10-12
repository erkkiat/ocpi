# CPO API

This directory and specifically the `api.py` file contains the implementation of the CPO API.
The API provides our CPO customer a shortcut to roaming networks. The simplified API is based on the OCPI protocol,
but suits Hubject OICP as well.

These are the functions and classes involved in RFID and mobile app charging processes:

```mermaid
sequenceDiagram

    alt RFID Token process
        CPO->>SolidRoam: ocpi22.cpo.api.authorize()
        SolidRoam->>Gireve: POST OCPI Authorize
        SolidRoam->>CPO: CPOAuthorizationResponseSerializer
    else Mobile app process
        Gireve->>SolidRoam: POST OCPI START_SESSION
        SolidRoam->>CPO: CPOStartWebhookSerializer
        CPO->>SolidRoam: CommandResponseSerializer
    end
    
    CPO->>SolidRoam: start_transaction()
    SolidRoam->>Gireve: PUT OCPI Session
```
