# Token Authorization

1. Driver arrives at the charger and taps her RFID token on the charge point 
2. The CPO calls the `authorize` endpoint with the token_id
3. SolidRoam checks if the token is already authorized (in OCPI, successful authorizations are cached for 15 minutes)
4. SolidRoam checks if the token is known to us (the CPO)
5. If the token is not authorized at the moment, SolidRoam sends an OCPI `Authorize` request to the known MSP or in case of an unknown token, all connected MSPs and HUBs asynchronously (`authorize_with_msps()`)
6. The MSP checks the driver's credit and makes a credit reservation
6. The MSP responds to the HUB, the HUB responds to us
7. **We consider the fastest positive response only**

In the future, we want to wait a moment after the first positive response to see if we get a response from a cheaper HUB or a cheaper direct connection.
For example, Hubject set prices per charger and Gireve per transaction.

```mermaid
sequenceDiagram
    participant Driver
    participant CPO
    participant SolidRoam
    participant Gireve
    participant HUB

    Driver->>CPO: Tap RFID Token <br/> on the charging station
    CPO->>SolidRoam: call "authorize" endpoint
    alt Cached authorization
        SolidRoam->>SolidRoam: Do we already have a cached authorization?
        SolidRoam-->>CPO: Cached authorization response
    else New authorization
        par Asynchronous authorization request
            SolidRoam->>Gireve: OCPI Authorize (async)
            Gireve->>MSP: OCPI Authorize
            SolidRoam->>Porsche: OCPI Authorize (async)
            SolidRoam->>Hubject: OICP ERoamingAuthorizeStart (async)
            Hubject->>MSP: OICP ERoamingAuthorizeStart

            MSP->>Gireve: Authorization response
            Gireve->>SolidRoam: Authorization response

            MSP->>Hubject: OICP ERoamingAuthorizationStart
            Hubject->>SolidRoam: OICP ERoamingAuthorizationStart
        end
        alt Token known
            SolidRoam->>Gireve: OCPI Authorize (for specific MSP)
            SolidRoam-->>CPO: Token is known and authorized
        else Token unknown
            SolidRoam->>HUB: Send OCPI `Authorize` request
            MSP-->>SolidRoam: Authorization response
            HUB-->>SolidRoam: Authorization response
            SolidRoam-->>CPO: Authorization response
        end
    end
```
