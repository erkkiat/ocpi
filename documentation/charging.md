# Charging

## Definitions

- CPO: Charge Point Operator
- MSP: Mobility Service Provider
- HUB: A central system that connects CPOs and MSPs
- OCPI: Open Charge Point Interface (industry standard)
- OICP: Open InterCharge Protocol (Hubject proprietary)
- Other proprietary roaming protocols exist

## The Charging Process

These endpoints are a part of the `CPO API`, which is called by a CPO which is our customer and who we provide 
roaming capabilities to. Authorize, Start Session and Meter Values are the endpoints, 
which rely on data stored in Redis.
Meter values is called hundreds of times during a charging session, the others only once per session.

```mermaid
graph TD
    %%{ init: { 'flowchart': { 'curve': 'catmullRom' } } }%%

    A[1. Authorize] -- Session <br/> Data --> R[(Redis)]
    R -->|Session <br/> Data| SS[2. Start Session]
    SS -- Update --> R
    R -->|Session <br/> Data| MV[3. Meter Values]
    MV -- Update --> R
    MV -- Called <br/> many times --> MV
    R -->|Session  <br/>Data| E[4. Stop Session]
    E -- Update --> R
    R -. Mirror <br/> session data? ..-> DB[(SQL <br/> Database)]
    DB -. Session Pull .-> MSP
    
    style DB fill:white,stroke:black,stroke-width:2px,color:black,stroke-dasharray: 5 5
    style MSP fill:white,stroke:black,stroke-width:2px,color:black,stroke-dasharray: 5 5
```

## The Sequence

1. When the CPO asks for Token Authorization through our simple CPO API, we send an authorization request to the HUB. 
Depending on which hub the MSP is connected to, we send the message over OCPI or OICP.
2. The HUB asks MSP for authorization.
3. MSP responds to HUB, HUB responds to us and we respond to the CPO.
4. If the RFID Token is authorized, we create an OCPI Session with status PENDING. 
4. The CPO calls the start_session endpoint, and we send the new OCPI Session to the HUB.

## Starting a charging session

Here we have the Gireve hub as an example, but it could be e-Clearing.net, Mobi-e or our own hub product.

```mermaid
sequenceDiagram
    actor Driver

    alt RFID Token process
        Driver->>CPO: Tap RFID Token <br/> on the charging station
        CPO->>SolidRoam: call "authorize" endpoint
        SolidRoam->>SolidRoam: Do we already have a cached authorization?
        SolidRoam-->>CPO: Cached authorization response
        SolidRoam->>Gireve: OCPI Authorize (async)
        Gireve->>MSP: OCPI Authorize
        MSP->>MSP: Generate authorization_reference
        MSP->>Gireve: Authorization response
        Gireve->>SolidRoam: Authorization response
        SolidRoam->>SolidRoam: Generate session_id
        SolidRoam->>SolidRoam: Cache authorization for 15 minutes
        SolidRoam->>CPO: Authorization response
    else Mobile app process
        Driver->>MSP: Click "Start charging" on a charging station on the map
        MSP->>Gireve: OCPI START_SESSION
        Gireve->>SolidRoam: OCPI START_SESSION
        SolidRoam->>CPO: Start Session
        CPO->>SolidRoam: Charger ready/not ready
    end
    
    CPO->>SolidRoam: Call start_transaction endpoint
    SolidRoam->>Gireve: New OCPI Session <br/>session_id
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
        SolidRoam->>Gireve: PATCH OCPI Session
        Gireve->>MSP: PATCH OCPI Session
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
    SolidRoam->>Gireve: PATCH OCPI Session <br/> (final)
    Gireve->>MSP: PATCH OCPI Session <br/> (final)
    SolidRoam->>CPO: CDR webhook <br/> (invoicing data)
    SolidRoam->>Gireve: CDR
    Gireve->>MSP: CDR
```
