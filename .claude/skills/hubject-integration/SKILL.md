---
name: hubject-integration
description: >
  Reference for the Hubject/OICP 2.3 integration in ocpiconnector. Load this skill
  for ANY task touching integrations/hubject/ — converters, schemas, services, API
  endpoints, or tests. Also load when working on EVSE data push, pricing products,
  CDR forwarding to Hubject, token authorization via Hubject, or remote start/stop
  commands routed through the Hubject network. If you see OperatorID, EvseID in
  OICP format, eRoaming, or HBS in the code or question, load this skill.
---

# Hubject / OICP 2.3 Integration

Spec source: https://github.com/hubject/oicp/tree/master/OICP-2.3

Implementation: `integrations/hubject/`

---

## Codebase layout

| File | Purpose |
|---|---|
| `services.py` | All Hubject API calls (push EVSE data, push status, send CDR, authorize, remote commands) |
| `schemas.py` | Pydantic models for all OICP 2.3 request/response bodies |
| `api.py` | Django Ninja endpoints that Hubject calls inbound (remote start/stop) + internal trigger endpoints |
| `ocpi_to_oicp_converter.py` | OCPI Session → OICP ChargingNotification (Start/Progress/End) |
| `oicp_to_ocpi_converter.py` | OICP AuthorizationStart response → OCPI 2.2.1 AuthorizationInfo |
| `solid_to_hubject_converter.py` | OCPI Location/Tariff/CDR → OICP EvseDataRecord/PricingProduct/CDR |
| `exceptions.py` | `HubjectRemoteCommandError` for remote command failures |
| `urls.py` | Router — certificate auth on all inbound Hubject endpoints |

---

## Authentication

All requests use **mutual TLS** — Hubject validates the CPO's SSL client certificate against the registered OperatorID. If the certificate and OperatorID don't match, Hubject returns status code `017 Unauthorized Access`.

In the codebase:
- `get_certificate_loaded_request(cred_id)` builds an `aiohttp` session with the correct SSL context
- `CredentialsRepository.find_hubject_credentials_role()` retrieves the Hubject `CredentialsRole`
- `_get_hubject_credentials_id()` is `@lru_cache(maxsize=1)` — credential lookups are cached

Required env vars:
```
HUBJECT_OPERATOR_ID          # e.g. "DE*ABC"
HUBJECT_URL                  # Hubject base URL
ENABLE_HUBJECT               # Feature flag — check before calling any Hubject service
DEFAULT_OICP_PRICE           # Fallback tariff price (must be >= 0)
DEFAULT_OICP_CURRENCY        # e.g. "EUR"
DEFAULT_OICP_PRICE_REFERENCE # "KILOWATT_HOUR" | "HOUR" | "MINUTE"
```

---

## Services the CPO must implement (inbound from Hubject)

| Operation | Version | Endpoint in api.py |
|---|---|---|
| eRoamingAuthorizeRemoteStart | V2.1 | `POST /api/oicp/charging/v21/providers/{provider_id}/authorize-remote/start` |
| eRoamingAuthorizeRemoteStop | V2.1 | `POST /api/oicp/charging/v21/providers/{provider_id}/authorize-remote/stop` |

Both must respond within **10 seconds** including network roundtrip. Return `eRoamingAcknowledgement`.

---

## Services the CPO sends to Hubject (outbound)

| Operation | Version | Description |
|---|---|---|
| eRoamingAuthorizeStart | V2.1 | Token authorization at charge point |
| eRoamingPushEvseData | V2.3 | Full load or delta of EVSE records |
| eRoamingPushEvseStatus | V2.1 | EVSE availability status updates |
| eRoamingChargingNotification | V1.1 | Session start / progress / end events |
| eRoamingPushPricingProductData | V1.0 | Tariff/pricing product upload |
| eRoamingPushEvsePricing | V1.0 | Map EVSEs to pricing products |
| eRoamingChargeDetailRecord | V2.2 | CDR after session ends |

---

## Critical protocol rules

### Sequential data push — never parallelize
Data push requests for the same operation (e.g. two EVSE full loads) **must** be sent sequentially. If sent in parallel, Hubject processes them in parallel and they can overtake each other, causing the later request to be overwritten by the earlier one. This is why all push tasks go through Celery with `.delay()`.

### SessionID ownership
Hubject creates the `SessionID` (UUID) after the first `AuthorizeStart` or `AuthorizeRemoteStart`. Every subsequent operation in the same session **must** include this `SessionID`. Store it as `session.hub_session_id`. CDRs sent to Hubject **must** use `hub_session_id`, not the OCPI `session.uid`.

### CDR: one per session
Hubject accepts exactly **one CDR per SessionID**. Sending a duplicate returns an error.

### Timestamps: include timezone offset
All datetime values must include a timezone offset (`YYYY-MM-DDThh:mm:ss+hh:mm`). CPOs must use the timezone of the charge point location, not UTC, to support time-based tariffs.

---

## ID formats

| ID | Pattern | Notes |
|---|---|---|
| EvseID (ISO) | `^[A-Za-z]{2}\*?[A-Za-z0-9]{3}\*?E[A-Za-z0-9\*]{1,30}$` | The `E` before the serial part is mandatory |
| EvseID (DIN) | `^\+?[0-9]{1,3}\*[0-9]{3}\*[0-9\*]{1,32}$` | Legacy, avoid for new EVSEs |
| OperatorID | `^([A-Za-z]{2}\*?[A-Za-z0-9]{3})\|(\+?[0-9]{1,3}\*[0-9]{3})$` | e.g. `DE*ABC` |
| ProviderID | Same pattern as OperatorID | e.g. `DE*8EO` or `DE-8EO` (both accepted) |
| SessionID | UUID: `^[A-Za-z0-9]{8}(-[A-Za-z0-9]{4}){3}-[A-Za-z0-9]{12}$` | Hubject-generated |
| EvcoID | ISO: 15 chars / DIN: 14 chars | Electric Vehicle Contract ID |
| ProductID | Max 50 chars | Pricing product identifier |

---

## OCPI → OICP conversion rules (non-obvious)

### EVSE ID: inject the "E" if missing
OCPI EVSE UIDs don't always include the mandatory `E` separator. The converter patches this:
```python
# FI*SMP*34567 → FI*SMP*E34567
hubject_evse_id = regex.sub(r"^([A-Za-z]{2}\*[A-Za-z]+\*)(?!E)", r"\1E", evse_id)
```
Always run this transformation before sending any EvseID to Hubject.

### Address: country-specific parsing
`AddressIso19773Type` requires separate `Street` and `HouseNum` fields, but OCPI stores a combined address string. The converter uses country-specific regex to split them:
- France has a different address format than DE/NL/FI
- Falls back to a general pattern if country-specific fails
- Returns `"-"` for components it cannot parse — this satisfies Hubject's mandatory field but is lossy

### Pricing ProductID: 50-char limit
`ProductID` = `{ocpi_tariff_uid}*{external_id}`. If this exceeds 50 chars, truncate `external_id`:
```python
# external_id[:6] + "_" + external_id[-6:]  — preserves prefix and suffix
product_id = f"{ocpi_tariff_uid}*{truncated_external_id}"
```

### Pricing provider: wildcard
EVSE pricing is pushed with `ProviderID = "*"` (offer-to-all). Hubject accepts a single value here, not a list — despite the spec suggesting a list is possible.

### Calibration law (Germany only)
`CalibrationLawDataAvailability`:
- `"Local"` — if the EVSE is in Germany (`country == "DEU"`)
- `"Not_Available"` — all other countries

Signed metering values in CDRs are only included when `CalibrationLawDataAvailability == "External"`.

### Identification type mapping
| OCPI token_type | OICP Identification |
|---|---|
| `RFID`, `AD_HOC_USER`, `OTHER` | `RFIDMifareFamilyIdentification(UID=token_uid)` |
| `APP_USER` | `RemoteIdentification(EvcoID=contract_id)` |

Do not use `RFIDIdentification` for authorization — the spec requires `RFIDMifareFamilyIdentification` for RFID auth.

### EVSE status mapping
| OCPI status | OICP EvseStatus |
|---|---|
| `AVAILABLE` | `Available` |
| `BLOCKED`, `CHARGING` | `Occupied` |
| `INOPERATIVE`, `OUTOFORDER`, `REMOVED` | `OutOfService` |
| `RESERVED` | `Reserved` |
| `UNKNOWN` | `Unknown` |

### ChargingNotification: skip zero-energy progress
Progress notifications where `consumed_energy == 0` are silently dropped — sending them adds noise and can trigger Hubject-side warnings.

---

## OICP → OCPI conversion rules

### AuthorizationStart response → OCPI
- `StatusCode == "000"` is the only success code
- `ProviderID` format is `DE-8EO` or `DE*8EO` — strip the separator to get `(country_code="DE", party_id="8EO")`
- `AuthorizationStatus == "Authorized"` → OCPI `allowed = "ALLOWED"`, otherwise `"NOT_ALLOWED"`
- `token_type` is hardcoded to `"RFID"` in the OCPI response

---

## Remote command response: EVSE status → OICP error code

When Hubject sends a RemoteStart/Stop and the CPO cannot fulfill it, return:

| EVSE state | OICP status code | Meaning |
|---|---|---|
| `AVAILABLE` | `000` | Success |
| `BLOCKED`, `PLANNED`, `UNKNOWN` | `501` | Communication to EVSE failed |
| `CHARGING` | `602` | EVSE already in use |
| `INOPERATIVE`, `OUTOFORDER`, `REMOVED` | `700` | EVSE out of service |
| `RESERVED` | `601` | Already reserved |
| `None` / missing | `603` | Unknown EvseID |

---

## Status codes reference

| Code | Meaning |
|---|---|
| `000` | Success |
| `017` | Unauthorized — certificate/OperatorID mismatch |
| `300` | EMP not found |
| `400` | Session invalid or not found |
| `501` | Communication to charge point failed |
| `601` | EVSE already reserved |
| `602` | EVSE occupied / session already active |
| `603` | Unknown EvseID |
| `604` | EvseID not Hubject-compatible (`IsHubjectCompatible=false`) |
| `700` | EVSE out of service |

---

## Error handling patterns

```python
# Pydantic validation error from our schemas
ValidationError → HTTP 400, OICP status 022 "Data error"

# Hubject returns non-000 status
response.StatusCode != "000" → log warning with STATUS_CODE_TEXT mapping, do not raise

# Hubject field validation errors (e.g. bad PostalCode)
parse_hubject_validation_errors(response) → list of (record_index, field_name, evse_id)

# Network failures
TimeoutError | ClientConnectionError → HTTP 404, "GENERIC_SERVER_ERROR"
ClientError → HTTP 404, "GENERIC_SERVER_ERROR"
```

---

## OpeningTimes: grouping logic
`map_regular_hours_to_opening_times()` groups `RegularHours` by time period and detects patterns:
- All 7 days same hours → `Everyday`
- Mon–Fri → `Workdays`
- Sat–Sun → `Weekend`
- Otherwise → individual day entries

The resulting `OpeningTimes` list uses `On` (day pattern) and `Period` (time range) fields.

---

## Spec reference links

- Services & operations: [02_CPO_Services_and_Operations.asciidoc](https://github.com/hubject/oicp/blob/master/OICP-2.3/OICP%202.3%20CPO/02_CPO_Services_and_Operations.asciidoc)
- Data types: [03_CPO_Data_Types.asciidoc](https://github.com/hubject/oicp/blob/master/OICP-2.3/OICP%202.3%20CPO/03_CPO_Data_Types.asciidoc)
- Communication paradigms: [01_CPO_Communication_Paradigms.asciidoc](https://github.com/hubject/oicp/blob/master/OICP-2.3/OICP%202.3%20CPO/01_CPO_Communication_Paradigms.asciidoc)
