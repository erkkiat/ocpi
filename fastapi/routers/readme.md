# FastAPI/NinjaAPI routers

## Introduction

When we were providing compatibility testing tools, Django Rest was the way to go.
The DRF endpoints provide a browsable HTML interface with diagrams and explanations about the process.
The FastAPI routers must not be mixed with the Django Rest routers, as the endpoints work together in sequence 
and their data needs differ.

## Definitions

- CPO: Charge Point Operator
- MSP: Mobility Service Provider
- HUB: A central system that connects CPOs and MSPs
- OCPI: Open Charge Point Interface (industry standard)
- OICP: Open InterCharge Protocol (Hubject proprietary)
- Other proprietary roaming protocols exist

## Charging process

1. When the CPO asks for Token Authorization through our simple CPO API, we send an authorization request to the HUB. 
Depending on which hub the MSP is connected to, we send the message over OCPI or OICP.
2. The HUB asks MSP for authorization.
3. MSP responds to HUB, HUB responds to us and we respond to the CPO.
4. If the RFID Token is authorized, we create an OCPI Session with status PENDING. 
4. The CPO calls the start_session endpoint, and we send the new OCPI Session to the HUB.

Let's use Gireve hub as an example, but it could be e-Clearing.net, Mobi-e or our own hub product.

```mermaid
sequenceDiagram
    actor Driver
    
    alt RFID Token process
    Driver->>CPO: Tap RFID Token <br/> on the charging station
        CPO->>SolidRoam: call "authorize" endpoint
        SolidRoam->>Gireve: OCPI Authorize
        Gireve->>MSP: Authorize Token
        MSP->>Gireve: Authorization response
        Gireve->>SolidRoam: Authorization response
        SolidRoam->>CPO: Authorization response
    else Mobile app process
        Driver->>MSP: Click "Start charging" on a charging station on the map
        MSP->>Gireve: OCPI START_SESSION
        Gireve->>SolidRoam: OCPI START_SESSION
        SolidRoam->>CPO: Start Session
        CPO->>SolidRoam: Charger ready/not ready
    end
    
    CPO->>SolidRoam: Call start_transaction endpoint
    SolidRoam->>Gireve: New OCPI Session
    Gireve->>MSP: New OCPI Session
```

## Meter values during a charging session

After the Session has been established, the CPO sends us meter values. The meter values contain:
- kWh charged so far 
- The power at this moment
- In the case of DC charging also the State of Charge (SoC)

```mermaid
sequenceDiagram
    participant CPO
    participant SolidRoam
    participant Gireve
    participant MSP
    actor Driver
    
    loop Repeats until Session is finished
        CPO->>SolidRoam: Meter Values <br/> over MQTT <br/> (kWh, power, SoC)
        SolidRoam->>Gireve: OCPI Meter Values
        Gireve->>MSP: OCPI Meter Values
        MSP-->>Driver: Show charging status
    end
```

## Stopping an ongoing charging session

```mermaid
sequenceDiagram
    actor Driver
    participant CPO
    participant SolidRoam
    participant Gireve
    participant MSP
    
    alt RFID Token process
    Driver->>CPO: Tap RFID Token <br/> on the charging station once more
        CPO->>SolidRoam: call "stop_transaction" endpoint
    else Mobile app process
        Driver->>MSP: Click "Stop charging"
        MSP->>Gireve: OCPI STOP_SESSION
        Gireve->>SolidRoam: OCPI STOP_SESSION
        SolidRoam->>CPO: Stop Session webhook
    end
    SolidRoam->>Gireve: Final OCPI Session
    Gireve->>MSP: Final OCPI Session
    SolidRoam->>CPO: CDR<br/>(invoicing data)
    SolidRoam->>Gireve: CDR
    Gireve->>MSP: CDR
```
