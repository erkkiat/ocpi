# CPO API

This directory and specifically the `api.py` file contains the implementation of the CPO API.
The API provides our CPO customer a shortcut to roaming networks. The simplified API is based on the OCPI protocol,
but suits Hubject OICP as well.

These are the elements involved in the optimised RFID and mobile app charging processes:

```mermaid
sequenceDiagram

    alt RFID Token process
        CPO->>SolidRoam: ocpi22.cpo.api.authorize()
        SolidRoam->>Gireve: POST OCPI Authorize
        SolidRoam->>CPO: CPOAuthorizationResponseSerializer
    else Mobile app process
        Gireve->>SolidRoam: ocpi22.commands.commands.start_session()
        SolidRoam->>CPO: CPOStartWebhookSerializer
        CPO->>SolidRoam: CommandResponseSerializer
    end

    CPO->>SolidRoam: start_transaction()
    SolidRoam->>CPO: CpoSessionSerializer
    SolidRoam->>Gireve: PUT OCPI Session
    loop Repeats until Session is finished
    CPO->>SolidRoam: ocpi22.cpo.mqtt.tasks.process_meter_values()
    SolidRoam->>Gireve: PATCH OCPI Session
    end

    alt RFID Token process
        CPO->>SolidRoam: ocpi22.cpo.api.stop_transaction()
        SolidRoam->>CPO: CpoSessionSerializer
    else Mobile app process
        Gireve->>SolidRoam: ocpi22.commands.commands.stop_session()
        SolidRoam->>CPO: CPOStopWebhookSerializer
        CPO->>SolidRoam: CommandResponseSerializer
    end

    SolidRoam->>Gireve: POST OCPI Session
    SolidRoam->>Gireve: POST OCPI CDR
    SolidRoam->>CPO: InvoicingCallbackSerializer
```
