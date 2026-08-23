# CPMS to SolidRoam Roaming API Integration Prompt

You are tasked with integrating a Charge Point Management System (CPMS) with the SolidRoam ocpiconnector CPO API to enable RFID charging session roaming. Your goal is to implement the OCPP-to-SolidRoam-API relay that maps OCPP messages to SolidRoam HTTP endpoints.

## Context

The CPMS receives OCPP messages from charge points and needs to relay authorization and transaction data to SolidRoam's roaming network. This enables drivers from partner eMSPs to charge at your locations using their RFID cards.

## SolidRoam API Overview

**Base URL**: `https://<solidroam-host>/api/cpo/v2/chargepoint/`
**Authentication**: HTTP Basic Auth with admin credentials
**Timestamps**: Always include UTC timestamps in all API calls for accurate billing

## Key API Endpoints

### 1. Authorize (POST /authorize/)
Authorizes an RFID token for charging at a specific EVSE.

**Request**:
```json
{
  "evse_id": "BE*SMP*E1234",
  "token_id": "DE*822*E123456789"
}
```

**Response** (if allowed):
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

**Critical**: Save the `session_id` for all subsequent calls (start, meter, stop).

### 2. Start Transaction (POST /start_transaction/)
Starts the charging session after authorization.

**Request**:
```json
{
  "session_id": "SESSION-UID-ABCD-1234",
  "connector_id": "1",
  "start_kwh": 0.0,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### 3. Meter Values (POST /meter_values/)
Updates session progress with current meter readings. Call every 10-30 seconds.

**Request**:
```json
{
  "session": "SESSION-UID-ABCD-1234",
  "kwh": 5.5,
  "soc": 65.0,
  "power": 22.0,
  "timestamp": "2024-01-01T12:15:00Z"
}
```

### 4. Stop Transaction (POST /stop_transaction/)
Ends the charging session and creates the Charge Detail Record (CDR).

**Request**:
```json
{
  "session_id": "SESSION-UID-ABCD-1234",
  "stop_kwh": 25.5,
  "timestamp": "2024-01-01T13:00:00Z"
}
```

### 5. Status Change (POST /status_change/)
Updates EVSE availability status to the roaming network.

**Request**:
```json
{
  "evse_uid": "BE*SMP*E1234",
  "status": "CHARGING",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## OCPP to SolidRoam Field Mappings

### OCPP 1.6 Mappings
- `Authorize.idTag` → `token_id`
- `Authorize.locationId` → `evse_id`
- `StartTransaction.connectorId` → `connector_id`
- `StartTransaction.meterStart` → `start_kwh`
- `MeterValues.meterValue[0].value` → `kwh` (convert Wh to kWh)
- `StopTransaction.meterStop` → `stop_kwh`
- `StatusNotification.status` → `status` (use OCPP to OCPI mapping table below)

### OCPP 2.0.1 Mappings
- `Authorize.idToken.idToken` → `token_id`
- `Authorize.evseId` → `evse_id`
- `TransactionEvent.connectorId` → `connector_id`
- `TransactionEvent.totalEnergy` → `kwh` (convert Wh to kWh)
- `TransactionEvent.eventType` → determines flow (Started/Updated/Ended)

## Integration Architecture

Choose one of the following approaches based on your CPMS architecture:

### Approach 1: OCPP Processor Interception (Recommended for centralized OCPP processing)
Intercept OCPP messages in your OCPP processor, map fields, call SolidRoam API synchronously, return OCPP response to charge point.

**Pros**: Centralized integration, easier debugging, consistent error handling
**Cons**: Requires OCPP processor modification, may add latency

### Approach 2: MQTT Message Relay (Recommended for event-driven architectures)
Subscribe to OCPP MQTT topics, parse and map messages asynchronously, call SolidRoam API with retry logic.

**Pros**: Decoupled from OCPP processor, non-blocking, scalable
**Cons**: Requires MQTT infrastructure, complex error handling

## RFID Charging Session Flow

1. Driver taps RFID card
2. CPMS receives OCPP Authorize
3. Call POST /authorize/ with evse_id and token_id
4. If allowed: Save session_id from response
5. CPMS starts charging (OCPP StartTransaction)
6. Call POST /start_transaction/ with session_id and connector_id
7. Call POST /status_change/ with status=CHARGING
8. Periodically (every 10-30s): Call POST /meter_values/ with session_id and current kwh
9. Driver unplugs vehicle
10. Call POST /stop_transaction/ with session_id and stop_kwh
11. Call POST /status_change/ with the updated status from the OCPP message

## Error Handling

**HTTP Status Codes**:
- 200 OK: Success, continue flow
- 400 Bad Request: Invalid format, fix and retry
- 401 Unauthorized: Auth failed, check credentials/token
- 403 Forbidden: Session not active, check session status
- 404 Not Found: Resource not found, verify IDs
- 409 Conflict: Resource conflict (EVSE occupied or session completed)

**Retry Strategy**: Implement exponential backoff with max 3 retries, 10-second timeout per request.

**Error Recovery**:
- Authorize fails: Do not allow charging, display error to driver
- Start fails: Cancel charging session, return to available state
- Meter values fail: Continue locally, retry on next update
- Stop fails: Log error, mark session completed locally, contact support

## Implementation Requirements

1. **Session Management**: Store session_id after successful authorize, use for all subsequent calls
2. **Timestamp Handling**: Always include UTC timestamps in all API calls
3. **Unit Conversion**: Convert OCPP Wh values to kWh for SolidRoam (divide by 1000)
4. **Error Logging**: Log all API calls with request payload, response status, timestamp
5. **Configuration**: Make SolidRoam base URL, username, and password configurable
6. **Testing**: Implement integration tests against SolidRoam test server

## Testing

Write integration tests that:
1. Test authorize with valid and invalid tokens
2. Test complete session flow (authorize → start → meter → stop)
3. Test status change updates
4. Test error scenarios (401, 404, timeout)
5. Use environment variables for test server configuration

- Do not simulate, use real API calls.
- Tests must call your new integration business logic, not just send some HTTP requests to SolidRoam. The SolidRoam APIs have been tested by SolidRoam.

## Configuration Example

```bash
SOLIDROAM_BASE_URL=https://test.solidroam.com/api/cpo/v2/chargepoint
SOLIDROAM_USER=test_admin
SOLIDROAM_PASSWORD=test_password
```

## Your Task

Implement the CPMS to SolidRoam integration following the specifications above. Choose the appropriate architecture approach for your system, implement the field mappings, handle errors appropriately, and write comprehensive tests. Ensure the integration is configurable and production-ready.
