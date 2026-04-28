---
name: ocpi-spec
description: >
  Canonical reference for OCPI 2.2.1 as implemented in ocpiconnector. Load this
  skill for any task touching credentials handshake, token authorization, session
  lifecycle, CDR structure, roaming hub routing, module roles (SENDER/RECEIVER),
  pagination headers, or OCPI response envelope format. Do not rely on memory for
  field cardinalities, required headers, role definitions, or URL structures —
  always consult this skill. Also load when debugging 401s, wrong role errors,
  missing headers, or hub routing failures.
---

# OCPI 2.2.1 — Key Spec Reference

Source: https://github.com/ocpi/ocpi/tree/2.2.1

---

## Authentication and headers

### Authorization header format
```
Authorization: Token <credentials_token>
```
Two distinct token types — never confuse them:
- **Credentials token** — exchanged via credentials module, used for API auth
- **Driver token** — exchanged via tokens module, used for EV charging auth

### Routing headers (functional modules only)
Required on all requests/responses to/from functional modules (Tokens, Locations,
Sessions, CDRs, Commands, Tariffs, etc.):
```
OCPI-From-Country-Code: NL
OCPI-From-Party-Id:     TNM
OCPI-To-Country-Code:   BE
OCPI-To-Party-Id:       ABC
```
**NOT used** on configuration modules: Credentials, Versions, HubClientInfo.

### OCPI response envelope
All responses:
```json
{
  "data": {},
  "status_code": 1000,
  "status_message": "Success",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

Common status codes:
| Code | Meaning |
|---|---|
| 1000 | Success |
| 2001 | Invalid or missing parameters |
| 2002 | Not enough information |
| 2003 | Unknown Location |
| 3000 | Server error |

HTTP 401 if credentials token missing or unrecognised.

---

## Credentials module

### Registration flow (Sender-initiates)
1. Sender has CREDENTIALS_TOKEN_A (pre-shared out-of-band)
2. Sender fetches Receiver's versions using TOKEN_A
3. Sender POSTs credentials endpoint with TOKEN_B + Sender's versions URL
4. Receiver stores TOKEN_B, fetches Sender's version details, generates TOKEN_C
5. Receiver returns TOKEN_C in response
6. Sender stores TOKEN_C for future requests; discards TOKEN_A

ocpiconnector supports both MSP-initiates and SolidRoam-initiates toggle.

### Credentials object
```json
{
  "token": "IpbJOXxkxOAuKR92z0nEcmVF3Qw09VG7I7d/WCg0koM=",
  "url": "https://example.com/ocpi/versions",
  "roles": [
    {
      "role": "CPO",
      "party_id": "TNM",
      "country_code": "NL",
      "business_details": {"name": "TheNewMotion"}
    }
  ]
}
```

### Endpoints
- `GET /ocpi/2.2.1/credentials` — retrieve credentials
- `POST /ocpi/2.2.1/credentials` — register (initial handshake)
- `PUT /ocpi/2.2.1/credentials` — update credentials
- `DELETE /ocpi/2.2.1/credentials` — unregister

---

## Module roles: SENDER vs RECEIVER

| Module | Sender (data owner) | Receiver |
|---|---|---|
| Locations | CPO | eMSP |
| Sessions | CPO | eMSP |
| CDRs | CPO | eMSP |
| Tariffs | CPO | eMSP |
| Tokens | eMSP | CPO |
| Commands | eMSP (initiates) | CPO (receives) |
| Payments (DirectPayment) | PTP | CPO |

For hub routing: ocpiconnector forwards using its own `OCPI-From-*` headers.
Downstream clients respond with hub's party info in `OCPI-To-*`.

---

## Tokens module

### Token object (key fields)
| Field | Type | Card | Notes |
|---|---|---|---|
| `country_code` | CiString[2] | 1 | Issuing eMSP country |
| `party_id` | CiString[3] | 1 | Issuing eMSP party ID |
| `uid` | CiString[36] | 1 | Token UID (on card/app) |
| `type` | TokenType | 1 | `RFID`, `APP_USER`, `OTHER`, `AD_HOC_USER` |
| `contract_id` | CiString[36] | 1 | eMSP contract identifier |
| `valid` | boolean | 1 | Whether token is currently valid |
| `whitelist` | WhitelistType | 1 | `ALWAYS`, `NEVER`, `ALLOWED`, `ALLOWED_OFFLINE` |
| `last_updated` | DateTime | 1 | |

### Whitelist behaviour
| Value | CPO behaviour |
|---|---|
| `ALWAYS` | Accept without real-time auth |
| `NEVER` | Always do real-time auth |
| `ALLOWED` | May do real-time auth, not required |
| `ALLOWED_OFFLINE` | Accept offline if real-time unavailable |

`valid=false` does NOT skip real-time auth — whitelist rules always apply.

### Real-time authorization
```
POST /ocpi/emsp/2.2.1/tokens/{token_uid}/authorize
```
Optional body: `{"location_id": "...", "evse_uids": [...]}`

Response `AuthorizationInfo.allowed` values:
`ALLOWED`, `BLOCKED`, `EXPIRED`, `NO_CREDIT`, `NOT_ALLOWED`

**ocpiconnector fix**: When eMSP returns NOT_ALLOWED/error, early-return before
serializer validation — never create fake token data.

---

## Sessions module

> For the full end-to-end flow (plug-in → auth → ACTIVE → CDR, both RFID and remote
> command paths, Hubject branch), read:
> `.claude/skills/ocpi-spec/references/session_lifecycle.md`
> Load it when working on anything touching session creation, auth flow, meter values,
> stop transaction, CDR trigger, or Hubject session routing.

### Status states
| Status | Meaning |
|---|---|
| `PENDING` | After auth, before charge starts. **Never sent to MSP.** |
| `ACTIVE` | Charge point confirmed start. First MSP PUT happens here. |
| `RESERVATION` | Exists due to reservation, not yet charging. |
| `COMPLETED` | Charge stopped. CDR created atomically in same transaction. |
| `INVALID` | Declared invalid after the fact. Not a normal transition. |

Sessions are never deleted — only move to COMPLETED or INVALID.

### auth_method (set once, never changed)
`WHITELIST` — token whitelisted, no MSP call |
`AUTH_REQUEST` — MSP responded to real-time auth |
`COMMAND` — session started via MSP START_SESSION command

### PUT vs PATCH
- **PUT** — full replace. Existing `charging_periods` replaced entirely.
- **PATCH** — partial. `charging_periods` in PATCH *adds* to existing ones. Omitting it changes nothing. Use PUT to remove/replace periods.

### Key fields
| Field | M/O | Notes |
|---|---|---|
| `id` | M | `session.uid` |
| `start_date_time` | M | Set when ACTIVE, not at PENDING creation |
| `end_date_time` | O | Set when COMPLETED |
| `kwh` | M | `max(stop_kwh - start_kwh, 0)` rounded to 3 dp |
| `cdr_token` | M | Token that started the session |
| `auth_method` | M | See above |
| `authorization_reference` | O | MSP reference — carried into CDR for matching |
| `evse_uid` / `connector_id` | M | `"#NA"` for reservations |
| `currency` | M | Derived from connector's first tariff |
| `charging_periods` | O | Updated on every meter value |
| `total_cost` | O | `excl_vat` and `incl_vat` variants |
| `status` | M | |
| `last_updated` | M | Always include in PATCH |

CPO pushes to eMSP:
```
PUT   /ocpi/emsp/2.2.1/sessions/{country_code}/{party_id}/{session_id}
PATCH /ocpi/emsp/2.2.1/sessions/{country_code}/{party_id}/{session_id}
```

---

## CDR module

### CDR object (key fields)
| Field | Type | Card | Notes |
|---|---|---|---|
| `id` | CiString[39] | 1 | |
| `start_date_time` | DateTime | 1 | |
| `end_date_time` | DateTime | 1 | |
| `session_id` | CiString[36] | ? | |
| `cdr_token` | CdrToken | 1 | |
| `auth_method` | AuthMethod | 1 | |
| `authorization_reference` | CiString[36] | ? | |
| `cdr_location` | CdrLocation | 1 | Location snapshot |
| `currency` | CiString[3] | 1 | ISO-4217 |
| `charging_periods` | ChargingPeriod | 1+ | |
| `total_cost` | Price | 1 | |
| `total_energy` | number | 1 | kWh |
| `total_time` | number | 1 | Hours |
| `last_updated` | DateTime | 1 | |

CPO POSTs CDR to eMSP:
```
POST /ocpi/emsp/2.2.1/cdrs/
```
Response `Location` header = URL of created CDR.

---

## Locations module

Hierarchy: `Location → EVSE[] → Connector[]`

EVSE status values:
`AVAILABLE`, `BLOCKED`, `CHARGING`, `INOPERATIVE`, `OUTOFORDER`, `PLANNED`,
`REMOVED`, `RESERVED`, `UNKNOWN`

CPO pushes updates:
```
PUT   /ocpi/emsp/2.2.1/locations/{country_code}/{party_id}/{location_id}
PATCH /ocpi/emsp/2.2.1/locations/{country_code}/{party_id}/{location_id}
PUT   /ocpi/emsp/2.2.1/locations/{country_code}/{party_id}/{location_id}/{evse_uid}
```

---

## Commands module

### CPO side endpoints (Receiver)
```
POST /ocpi/cpo/2.2.1/commands/START_SESSION/
POST /ocpi/cpo/2.2.1/commands/STOP_SESSION/
POST /ocpi/cpo/2.2.1/commands/RESERVE_NOW/
POST /ocpi/cpo/2.2.1/commands/CANCEL_RESERVATION/
POST /ocpi/cpo/2.2.1/commands/UNLOCK_CONNECTOR/
```

### Command result flow
1. eMSP POSTs command to CPO
2. CPO immediately responds: `{result: ACCEPTED/REJECTED, timeout: N}`
3. CPO executes command async via MQTT
4. CPO POSTs `CommandResult` to `response_url` from original command

### StartSession (key fields)
| Field | Card | Notes |
|---|---|---|
| `response_url` | 1 | Async result callback |
| `token` | 1 | Token to use |
| `location_id` | 1 | |
| `evse_uid` | ? | Required in DirectPayment context |
| `connector_id` | ? | Required in DirectPayment context |
| `authorization_reference` | ? | Required in DirectPayment context |

---

## Pagination

### Request parameters
```
?date_from=2019-01-28T12:00:00&date_to=2019-01-29T12:00:00&offset=50&limit=100
```

### Response headers
```
X-Total-Count: 4321
X-Limit: 100
Link: <https://...?offset=150&limit=100>; rel="next"
```

`Link` rel=next is required when `offset + limit < X-Total-Count`.

---

## Client-owned objects

URL pattern:
```
/ocpi/{role}/2.2.1/{module}/{country_code}/{party_id}/{object_id}
```

- CPO owns: Locations, Sessions, CDRs, Tariffs
- eMSP owns: Tokens
- PTP owns: Terminal, FinancialAdviceConfirmation (DirectPayment)

---

## Hub-specific (ocpiconnector as hub)

- Routes to downstream party based on `OCPI-To-*` headers
- Uses own `OCPI-From-*` when forwarding
- Broadcast Push: use for Tokens/Locations; NEVER for CDRs/Sessions
- Hubject: use `decode_country_code_and_party_id()` for dash-separated IDs like
  `"NL-TNM"` — never naive `split("-")`
