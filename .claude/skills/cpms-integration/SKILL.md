---
name: cpms-integration
description: >
  Integration guide for connecting a custom Charge Point Management System (CPMS) to the
  SolidRoam ocpiconnector CPO API. Load this skill when implementing OCPP-to-OCPI relay
  for RFID charging sessions, mapping OCPP messages to SolidRoam HTTP endpoints, or writing
  integration tests against the test server.
---

# CPMS Integration Guide

This skill provides comprehensive guidance for integrating a custom Charge Point Management System (CPMS) with the SolidRoam ocpiconnector CPO API for RFID charging sessions.

---

## Base URL and Authentication

### Base URL
```
https://<solidroam-host>/api/cpo/v2/chargepoint/
```

### Authentication
All CPO API endpoints use **HTTP Basic Authentication** with admin credentials.

**Note**: Code examples in this skill are shown in Python using the `requests` library, but the CPMS may be implemented in any programming language (Node.js, Java, Go, etc.) and any web/API framework. The HTTP request structure, fields, and endpoints remain the same across languages.

```python
import requests
from requests.auth import HTTPBasicAuth

auth = HTTPBasicAuth("admin_username", "admin_password")
```

**Note**: This is for initial integration. Production deployments may require API key authentication.

### Timestamp Best Practice

Although the `timestamp` field is optional in all API endpoints, **always include it** with the actual time from the charge point. This ensures accurate billing and session tracking even if network connectivity issues delay message delivery. Use UTC timezone for all timestamps.

---

## CPO API Endpoints

### 1. Authorize

**Endpoint**: `POST /api/cpo/v2/chargepoint/authorize/`

Authorizes an RFID token for charging at a specific EVSE. Creates an OCPI session in `PENDING` status if authorized.

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `evse_id` | string | EVSE UID (from your CPMS location data) |
| `token_id` | string | RFID token UID (hidden ID on the card/app) |

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `allowed` | enum | `ALLOWED` or `NOT_ALLOWED` |
| `token` | string | Token UID |
| `responding_party` | string | Party ID of the responding eMSP (e.g., `FI*MSP`) |
| `billed_to` | string | Party ID responsible for payment |
| `authorization_reference` | string | Unique reference from eMSP |
| `auth_method` | enum | `AUTH_REQUEST`, `WHITELIST`, or `COMMAND` |
| `session_id` | string | OCPI session ID (save this for subsequent calls) |

#### Example Request

```json
{
  "evse_id": "BE*SMP*E1234",
  "token_id": "DE*822*E123456789"
}
```

#### Example Response (Success)

```json
{
  "allowed": "ALLOWED",
  "token": "DE*822*E123456789",
  "responding_party": "DE*MSP",
  "billed_to": "DE*MSP",
  "authorization_reference": "AUTH-REF-12345",
  "auth_method": "AUTH_REQUEST",
  "session_id": "SESSION-UID-ABCD-1234"
}
```

#### Status Codes

- `200 OK` - Token authorized
- `400 Bad Request` - Invalid request format
- `401 Unauthorized` - Token not valid for charging
- `404 Not Found` - EVSE or token not found

---

### 2. Start Transaction

**Endpoint**: `POST /api/cpo/v2/chargepoint/start_transaction/`

Starts the charging session. Moves the OCPI session from `PENDING` to `ACTIVE`.

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | OCPI session ID from authorize response |
| `connector_id` | string | Connector ID used for charging |
| `start_kwh` | float | Optional. kWh reading at session start (default: 0.0) |
| `timestamp` | datetime | Optional. Session start timestamp (default: UTC now) |

#### Response Fields

Returns the full session object including:
- `session_id` - OCPI session ID
- `billed_to` - Party ID for billing
- `start_date_time` - Session start timestamp
- `start_kwh` - Starting kWh value
- `token` - Token information
- `auth_method` - Authorization method used
- `location_id` - Location UID
- `evse_uid` - EVSE UID
- `connector_id` - Connector ID
- `currency` - Session currency
- `total_cost_incl_vat` - Current cost (0 at start)
- `total_kwh` - Total kWh (0 at start)
- `status` - Session status (should be `ACTIVE`)
- `last_updated` - Last update timestamp

#### Example Request

```json
{
  "session_id": "SESSION-UID-ABCD-1234",
  "connector_id": "1",
  "start_kwh": 0.0,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

#### Example Response

```json
{
  "session_id": "SESSION-UID-ABCD-1234",
  "billed_to": "DE*MSP",
  "start_date_time": "2024-01-01T12:00:00Z",
  "start_kwh": 0.0,
  "stop_kwh": 0.0,
  "token": {
    "country_code": "DE",
    "party_id": "822",
    "token_id": "E123456789",
    "type": "RFID",
    "contract_id": "CONTRACT-123"
  },
  "auth_method": "AUTH_REQUEST",
  "authorization_reference": "AUTH-REF-12345",
  "location_id": "BE*SMP*LOC001",
  "evse_uid": "BE*SMP*E1234",
  "connector_id": "1",
  "currency": "EUR",
  "total_cost_incl_vat": 0.0,
  "total_cost_excl_vat": 0.0,
  "total_kwh": 0.0,
  "status": "ACTIVE",
  "last_updated": "2024-01-01T12:00:00Z"
}
```

#### Status Codes

- `200 OK` - Session started successfully
- `400 Bad Request` - Invalid request format
- `401 Unauthorized` - Token expired or invalid
- `404 Not Found` - Session or EVSE not found
- `409 Conflict` - EVSE already occupied

---

### 3. Meter Values

**Endpoint**: `POST /api/cpo/v2/chargepoint/meter_values/`

Updates the session progress with current meter readings. Call preferably every 30 seconds, but more frequent is also acceptable to simplify the implementation.

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `session` | string | OCPI session ID from authorize response |
| `kwh` | float | Current kWh measurement |
| `soc` | float | Optional. State of Charge (0-100) for DC charging |
| `power` | float | Optional. Current power in kW |
| `timestamp` | datetime | Optional. Timestamp of meter value (default: UTC now) |

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `status_text` | string | Status message |
| `session_id` | string | OCPI session ID |
| `start_kwh` | float | Starting kWh value |
| `now_kwh` | float | Current kWh value |
| `total_kwh` | float | Total kWh delivered |
| `power` | float | Current power (if provided) |
| `price` | float | Current session cost |
| `soc` | float | State of charge (if provided) |

#### Example Request

```json
{
  "session": "SESSION-UID-ABCD-1234",
  "kwh": 5.5,
  "soc": 65.0,
  "power": 22.0,
  "timestamp": "2024-01-01T12:15:00Z"
}
```

#### Example Response

```json
{
  "status_text": "Session updated",
  "session_id": "SESSION-UID-ABCD-1234",
  "start_kwh": 0.0,
  "now_kwh": 5.5,
  "total_kwh": 5.5,
  "power": 22.0,
  "price": 2.75,
  "soc": 65.0
}
```

#### Status Codes

- `200 OK` - Session updated
- `400 Bad Request` - Invalid request format
- `403 Forbidden` - Session not active
- `404 Not Found` - Session not found
- `409 Conflict` - Tariff misconfigured

#### Meter Value Frequency

The MSP may specify a minimum meter value frequency via OCPI credentials. If meter values are sent too frequently, they will be skipped with a `200 OK` response and a status message indicating the skip.

---

### 4. Stop Transaction

**Endpoint**: `POST /api/cpo/v2/chargepoint/stop_transaction/`

Ends the charging session and creates the Charge Detail Record (CDR). Call after the vehicle is unplugged.

#### OCPP Trigger Message

The vehicle unplugged event is indicated by different OCPP messages depending on the protocol version:

- **OCPP 1.6**: The charge point sends a `StopTransaction` message to the central system when the cable is disconnected
- **OCPP 2.0.1**: The charge point sends a `TransactionEvent` message with `eventType: "Ended"` when the cable is disconnected

Your CPMS should intercept these messages and relay them to the SolidRoam `stop_transaction` endpoint.

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | OCPI session ID |
| `stop_kwh` | float | Final kWh reading from charger |
| `timestamp` | datetime | Optional. Stop timestamp (default: UTC now) |

#### Response Fields

Returns the completed session object with final values:
- `session_id` - OCPI session ID
- `end_date_time` - Session end timestamp
- `stop_kwh` - Final kWh value
- `total_kwh` - Total kWh delivered
- `total_cost_incl_vat` - Final cost including VAT
- `total_cost_excl_vat` - Final cost excluding VAT
- `status` - Session status (should be `COMPLETED`)

#### Example Request

```json
{
  "session_id": "SESSION-UID-ABCD-1234",
  "stop_kwh": 25.5,
  "timestamp": "2024-01-01T13:00:00Z"
}
```

#### Example Response

```json
{
  "session_id": "SESSION-UID-ABCD-1234",
  "billed_to": "DE*MSP",
  "start_date_time": "2024-01-01T12:00:00Z",
  "end_date_time": "2024-01-01T13:00:00Z",
  "start_kwh": 0.0,
  "stop_kwh": 25.5,
  "token": {
    "country_code": "DE",
    "party_id": "822",
    "token_id": "E123456789",
    "type": "RFID",
    "contract_id": "CONTRACT-123"
  },
  "auth_method": "AUTH_REQUEST",
  "authorization_reference": "AUTH-REF-12345",
  "location_id": "BE*SMP*LOC001",
  "evse_uid": "BE*SMP*E1234",
  "connector_id": "1",
  "currency": "EUR",
  "total_cost_incl_vat": 12.75,
  "total_cost_excl_vat": 10.62,
  "total_kwh": 25.5,
  "status": "COMPLETED",
  "last_updated": "2024-01-01T13:00:00Z"
}
```

#### Status Codes

- `200 OK` - Session ended, CDR created
- `400 Bad Request` - Invalid request format
- `404 Not Found` - Session not found
- `409 Conflict` - Session already completed

---

### 5. Status Change

**Endpoint**: `POST /api/cpo/v2/chargepoint/status_change/`

Updates EVSE availability status to the roaming network. Call whenever charge point status changes to ensure accurate driver information.

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `evse_uid` | string | EVSE UID |
| `status` | enum | OCPP status (see mapping below) |
| `timestamp` | datetime | Optional. Status change timestamp (default: UTC now) |

#### OCPP to OCPI Status Mapping

| OCPP Status | OCPI Status |
|-------------|-------------|
| `AVAILABLE` | `AVAILABLE` |
| `PREPARING` | `AVAILABLE` |
| `CHARGING` | `CHARGING` |
| `SUSPENDEDEV` | `CHARGING` |
| `SUSPENDEDEVSE` | `CHARGING` |
| `FINISHING` | `CHARGING` |
| `RESERVED` | `RESERVED` |
| `UNAVAILABLE` | `CHARGING` |
| `FAULTED` | `OUTOFORDER` |

#### Example Request

```json
{
  "evse_uid": "BE*SMP*E1234",
  "status": "CHARGING",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

#### Example Response

```json
{
  "status_text": "EVSE status has been changed",
  "evse": "BE*SMP*E1234",
  "ocpi_status": "CHARGING",
  "ocpp_status": "CHARGING"
}
```

#### Status Codes

- `200 OK` - EVSE status updated
- `400 Bad Request` - Invalid request format
- `404 Not Found` - EVSE not found

---

## OCPP to SolidRoam Field Mappings

### OCPP 1.6 Mappings

| OCPP 1.6 Field | SolidRoam Field | Notes |
|----------------|-----------------|-------|
| `Authorize.idTag` | `token_id` | RFID tag ID |
| `Authorize.locationId` | `evse_id` | Location/EVSE identifier |
| `StartTransaction.idTag` | `token_id` | Retrieved from session context |
| `StartTransaction.connectorId` | `connector_id` | Direct mapping |
| `StartTransaction.meterStart` | `start_kwh` | Initial meter value |
| `StartTransaction.timestamp` | `timestamp` | Session start time |
| `MeterValues.connectorId` | `connector_id` | Retrieved from session context |
| `MeterValues.meterValue[0].value` | `kwh` | Cumulative energy in Wh, convert to kWh |
| `MeterValues.meterValue[0].timestamp` | `timestamp` | Meter reading time |
| `StopTransaction.idTag` | `token_id` | Retrieved from session context |
| `StopTransaction.meterStop` | `stop_kwh` | Final meter value |
| `StopTransaction.timestamp` | `timestamp` | Session end time |
| `StatusNotification.connectorId` | `evse_uid` | EVSE identifier |
| `StatusNotification.status` | `status` | Use mapping table above |
| `StatusNotification.timestamp` | `timestamp` | Status change time |

### OCPP 2.0.1 Mappings

| OCPP 2.0.1 Field | SolidRoam Field | Notes |
|------------------|-----------------|-------|
| `Authorize.idToken.idToken` | `token_id` | Token UID |
| `Authorize.idToken.type` | - | Used for token type validation |
| `Authorize.evseId` | `evse_id` | EVSE identifier |
| `RequestStartTransaction.idToken.idToken` | `token_id` | For remote start |
| `RequestStartTransaction.evseId` | `evse_id` | EVSE identifier |
| `TransactionEvent.connectorId` | `connector_id` | Direct mapping |
| `TransactionEvent.eventType` | - | Use to determine flow (Started/Updated/Ended) |
| `TransactionEvent.totalEnergy` | `kwh` | Energy in Wh, convert to kWh |
| `TransactionEvent.timestamp` | `timestamp` | Event timestamp |
| `TransactionEvent.chargingState` | `status` | Map to OCPI status |
| `Heartbeat.currentDateTime` | `timestamp` | For time synchronization |

### SOC (State of Charge) Mapping

| OCPP Version | Field | SolidRoam Field |
|--------------|-------|-----------------|
| OCPP 1.6 | `MeterValues.sampledValue[value="SoC"]` | `soc` |
| OCPP 2.0.1 | `TransactionEvent.stateOfCharge` | `soc` |

### Power Mapping

| OCPP Version | Field | SolidRoam Field |
|--------------|-------|-----------------|
| OCPP 1.6 | `MeterValues.sampledValue[measurand="Power.Active.Import"]` | `power` (convert W to kW) |
| OCPP 2.0.1 | `TransactionEvent.currentPower` | `power` (in kW) |

---

## Integration Architecture

### Approach 1: OCPP Processor Interception

**Best for**: CPMS with centralized OCPP message processing

```
Charge Point → OCPP Processor → SolidRoam API
```

#### Implementation Pattern

1. **Intercept OCPP messages** in your OCPP processor
2. **Map fields** using the tables above
3. **Call SolidRoam API** synchronously or asynchronously
4. **Return OCPP response** to charge point

#### Example Flow (Python-like pseudocode)

```python
def handle_authorize(ocpp_request):
    # Extract OCPP fields
    token_id = ocpp_request.idTag
    evse_id = ocpp_request.locationId or get_evse_for_connector(ocpp_request.connectorId)

    # Call SolidRoam API
    response = requests.post(
        f"{BASE_URL}/authorize/",
        json={"evse_id": evse_id, "token_id": token_id},
        auth=AUTH
    )

    # Map SolidRoam response to OCPP
    if response.json()["allowed"] == "ALLOWED":
        return ocpp_authorize_response(idTagInfo={"status": "Accepted"})
    else:
        return ocpp_authorize_response(idTagInfo={"status": "Blocked"})
```

#### Pros
- Centralized integration point
- Easier to debug and monitor
- Consistent error handling

#### Cons
- Requires modification of OCPP processor
- May introduce latency in OCPP message handling

---

### Approach 2: MQTT Message Relay

**Best for**: CPMS using MQTT for internal communication or event-driven architecture

```
Charge Point → MQTT Broker → Relay Service → SolidRoam API
```

#### Implementation Pattern

1. **Subscribe to OCPP MQTT topics** (or CPMS-internal topics)
2. **Parse and map** OCPP messages
3. **Call SolidRoam API** asynchronously
4. **Handle errors** with retry logic

#### Example Flow (Python-like pseudocode)

```python
import pika
import requests

def on_ocpp_message(ch, method, properties, body):
    ocpp_msg = json.loads(body)

    if ocpp_msg[2] == "Authorize":
        token_id = ocpp_msg[3]["idTag"]
        evse_id = ocpp_msg[3]["locationId"]

        try:
            response = requests.post(
                f"{BASE_URL}/authorize/",
                json={"evse_id": evse_id, "token_id": token_id},
                auth=AUTH,
                timeout=5
            )
            # Store session_id for subsequent calls
            session_id = response.json()["session_id"]
            store_session_mapping(token_id, session_id)
        except requests.RequestException as e:
            log_error(f"Failed to call SolidRoam API: {e}")
```

#### MQTT Topic Structure (Example)

```
ocpi/authorize           → Authorize messages
ocpi/start_transaction  → Start transaction messages
ocpi/meter_values       → Meter value updates
ocpi/stop_transaction   → Stop transaction messages
ocpi/status_change      → EVSE status changes
```

#### Pros
- Decoupled from OCPP processor
- Event-driven, non-blocking
- Scalable with multiple consumers

#### Cons
- Requires MQTT infrastructure
- Asynchronous error handling more complex
- Message ordering considerations

---

## RFID Charging Session Flow

### Complete Flow Sequence

```
1. Driver taps RFID card
   ↓
2. CPMS receives OCPP Authorize
   ↓
3. Call POST /authorize/ with evse_id and token_id
   ↓
4. If allowed: Save session_id from response
   ↓
5. CPMS starts charging (OCPP StartTransaction)
   ↓
6. Call POST /start_transaction/ with session_id and connector_id
   ↓
7. Call POST /status_change/ with status=CHARGING
   ↓
8. Periodically (every 10-15s):
   Call POST /meter_values/ with session_id and current kwh
   ↓
9. Driver unplugs vehicle
   ↓
10. Call POST /stop_transaction/ with session_id and stop_kwh
    ↓
11. Call POST /status_change/ with status=AVAILABLE
```

### Session ID Management

- **Store session_id** after successful authorize call
- **Use session_id** for all subsequent calls (start, meter_values, stop)
- **Session expires** in 15 minutes if not started
- **Session is unique** per charging session

### Error Recovery

- **Authorize fails**: Do not allow charging, display error to driver
- **Start fails**: Cancel charging session, return to available state
- **Meter values fail**: Continue locally, retry on next update
- **Stop fails**: Log error, mark session as completed locally, contact support

---

## Error Handling

### Common HTTP Status Codes

| Status | Meaning | Action |
|--------|---------|--------|
| `200 OK` | Success | Continue flow |
| `400 Bad Request` | Invalid format | Check request fields, fix and retry |
| `401 Unauthorized` | Auth failed | Check credentials, token may be invalid |
| `403 Forbidden` | Session not active | Check session status before meter values |
| `404 Not Found` | Resource not found | Verify EVSE, token, or session ID |
| `409 Conflict` | Resource conflict | EVSE occupied or session already completed |

### Retry Strategy

```python
import time
import requests
from requests.exceptions import RequestException

def call_solidroam_api(endpoint, data, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{BASE_URL}/{endpoint}/",
                json=data,
                auth=AUTH,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise
```

### Logging

Log all API calls with:
- Request payload
- Response status
- Response body (to be omitted in production)
- Timestamp
- Correlation ID (if available)

---

## Testability

The integration code should be triggerable by integration tests to verify against the SolidRoam test server.

### Test Configuration

```python
import os

SOLIDROAM_BASE_URL = os.getenv("SOLIDROAM_BASE_URL", "https://test.solidroam.com/api/cpo/v2/chargepoint")
SOLIDROAM_USER = os.getenv("SOLIDROAM_USER", "test_admin")
SOLIDROAM_PASSWORD = os.getenv("SOLIDROAM_PASSWORD", "test_password")
```

### Test Patterns

#### 1. Authorize Integration Test

```python
def test_authorize_integration():
    # Your integration function that calls SolidRoam
    result = handle_ocpp_authorize({
        "idTag": "DE*822*E123456789",
        "locationId": "BE*SMP*E1234"
    })

    # Verify the result structure
    assert "session_id" in result
    assert result["allowed"] in ["ALLOWED", "NOT_ALLOWED"]

    # Verify the session can be used for subsequent calls
    if result["allowed"] == "ALLOWED":
        start_result = handle_ocpp_start_transaction({
            "connectorId": "1",
            "meterStart": 0.0
        }, session_id=result["session_id"])
        assert start_result["status"] == "ACTIVE"
```

#### 2. Complete Session Flow Test

```python
def test_complete_session_flow():
    # Authorize
    auth_result = handle_ocpp_authorize({
        "idTag": "DE*822*E123456789",
        "locationId": "BE*SMP*E1234"
    })
    assert auth_result["allowed"] == "ALLOWED"
    session_id = auth_result["session_id"]

    # Start transaction
    start_result = handle_ocpp_start_transaction({
        "connectorId": "1",
        "meterStart": 0.0
    }, session_id=session_id)
    assert start_result["status"] == "ACTIVE"

    # Meter values
    meter_result = handle_ocpp_meter_values({
        "connectorId": "1",
        "meterValue": [{"value": "5500", "unit": "Wh"}]
    }, session_id=session_id)
    assert meter_result["total_kwh"] == 5.5

    # Stop transaction
    stop_result = handle_ocpp_stop_transaction({
        "meterStop": 25500
    }, session_id=session_id)
    assert stop_result["status"] == "COMPLETED"
```

#### 3. Status Change Test

```python
def test_status_change_integration():
    result = handle_ocpp_status_notification({
        "connectorId": "1",
        "status": "Charging"
    }, evse_uid="BE*SMP*E1234")
    assert result["ocpi_status"] == "CHARGING"
```

### Running Tests

```bash
# Run all integration tests
pytest tests/integration/ -v

# Run specific test
pytest tests/integration/test_cpms_integration.py::test_complete_session_flow -v

# Run against specific test server
SOLIDROAM_BASE_URL=https://custom-test-server.com/api/cpo/v2/chargepoint pytest tests/integration/ -v
```

---

## Quick Reference

### Endpoint Summary

| Operation | Method | Endpoint | Key Fields |
|-----------|--------|----------|------------|
| Authorize | POST | `/authorize/` | `evse_id`, `token_id` |
| Start | POST | `/start_transaction/` | `session_id`, `connector_id` |
| Meter | POST | `/meter_values/` | `session`, `kwh` |
| Stop | POST | `/stop_transaction/` | `session_id`, `stop_kwh` |
| Status | POST | `/status_change/` | `evse_uid`, `status` |

### Minimal Session Example

```python
import requests
from requests.auth import HTTPBasicAuth

BASE_URL = "https://solidroam.example.com/api/cpo/v2/chargepoint"
AUTH = HTTPBasicAuth("admin", "password")

# 1. Authorize
auth_resp = requests.post(f"{BASE_URL}/authorize/", json={
    "evse_id": "BE*SMP*E1234",
    "token_id": "DE*822*E123456789"
}, auth=AUTH).json()

session_id = auth_resp["session_id"]

# 2. Start
requests.post(f"{BASE_URL}/start_transaction/", json={
    "session_id": session_id,
    "connector_id": "1"
}, auth=AUTH)

# 3. Meter (repeat periodically)
requests.post(f"{BASE_URL}/meter_values/", json={
    "session": session_id,
    "kwh": 10.5
}, auth=AUTH)

# 4. Stop
requests.post(f"{BASE_URL}/stop_transaction/", json={
    "session_id": session_id,
    "stop_kwh": 25.5
}, auth=AUTH)
```

---

## Additional Resources

- **OCPI Specification**: https://github.com/ocpi/ocpi/tree/2.2.1
- **OCPP 1.6 Specification**: https://openchargealliance.org/
- **OCPP 2.0.1 Specification**: https://openchargealliance.org/
- **SolidRoam API Docs**: Contact SolidRoam for full API documentation
