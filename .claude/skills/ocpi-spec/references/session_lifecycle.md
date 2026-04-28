# Session Lifecycle — End-to-End Flow

## Path A — Driver-initiated (RFID tap / app)

```
Driver taps RFID at charge point
  │
  ▼
Charge point publishes MQTT authorize message
  → process_authorize_data()   [ocpi22/cpo/mqtt/services.py]
  → builds TokenDto(uid, adhoc=False if known token)
  │
  ▼
authorize_token()   [ocpi22/tokens/auth.py]
  ├─ AD-HOC token? → check session cache (15-min window) → return cached if hit
  └─ _authorize_token():
       ├─ Token in DB + whitelist=ALWAYS?
       │     → TokenAuthorization(allowed=ALLOWED, auth_method=WHITELIST)
       │     → No MSP call
       └─ Otherwise:
             → find_authorize_party_details() → MSP endpoint(s)
             → authorize_with_msps_sync()  [ocpi22/tokens/token_async.py]
                   POST /ocpi/cpo/2.2.1/tokens/{token_uid}/authorize  (async, 8s timeout)
                   RFID  → route to specific MSP
                   APP_USER/AD_HOC → broadcast, first ALLOWED wins
             → ALLOWED  → auth_method=AUTH_REQUEST
             → All fail  → TokenNotAuthorized
  │
  ├─ NOT_ALLOWED → publish rejection to charge point via MQTT — stop here
  │
  └─ ALLOWED → create_and_save_session()   [ocpi22/cpo/mqtt/services.py]
                  session.status        = PENDING
                  session.auth_method   = WHITELIST | AUTH_REQUEST
                  session.hub_session_id set if Hubject routed
                  ── No OCPI update sent to MSP (PENDING is suppressed) ──
  │
  ▼
publish TokenAuthorizationResponse(allowed, session_id) → charge point via MQTT
  │
  ▼
Charge point starts physically charging
POST /api/cpo/start_transaction/
  ├─ auth_method=COMMAND  → SessionService.start_command_session()
  │                              start_kwh = stop_kwh = reported value
  └─ AUTH_REQUEST/WHITELIST → SessionService.set_currency_and_start()
                                    connector resolved, currency set from tariff
  session.status = ACTIVE
  session.send_updates()  →  PUT /ocpi/emsp/2.2.1/sessions/…  (first update MSP sees)
  │
  ▼
Charge point sends meter values periodically via MQTT
  → process_meter_values_data()
  → update_meter_values_async Celery task  (queue=HIGH, expires=60s)
       skipped silently if session.status != ACTIVE
       throttled if too frequent
  → SessionService.update_meter_values():
         stop_kwh updated
         charging_periods updated
         price recalculated
  → session.send_updates(method="put")  →  PUT to MSP
  │
  ▼
Driver stops (RFID tap / button on charger)
POST /api/cpo/stop_transaction/
  └─ SessionService.stop_and_create_cdr()  [atomic DB transaction]
         status = COMPLETED,  end_date_time set
         final stop_kwh, charging_periods, price
         CdrService.get_or_create_cdr(session)  ← CDR created here
  → session.send_updates()  →  PUT to MSP  (final session state)
  → cdr.send_updates()      →  POST /ocpi/emsp/2.2.1/cdrs/
```

---

## Path B — MSP-initiated (remote START_SESSION command)

```
MSP sends OCPI command
POST /ocpi/cpo/2.2.1/commands/START_SESSION/
  Body: { response_url, token, location_id, evse_uid,
          connector_id, authorization_reference }
  │
  ▼
CPO responds immediately (sync): ACCEPTED | REJECTED
  Rejected if: EVSE occupied / EVSE not found / location not found /
               connector not found / no webhook configured
  │
  ▼
StartCommandService.start_session()   [ocpi22/commands/services.py]
  ├─ Active session on EVSE? → reject
  └─ create_session(auth_method=COMMAND, status=PENDING)
       Send webhook to charge point:
         { response_url, token, authorization_reference,
           evse_uid, connector_id, session_id }
  │
  ▼
Charge point starts, sends start_transaction
  → SessionService.start_command_session():
         status = ACTIVE,  start_kwh = stop_kwh = reported value
         sends ACCEPTED callback to MSP's response_url
  │
  ▼
Meter values, stop — identical to Path A
  │
  Stop may be MSP-initiated:
  POST /ocpi/cpo/2.2.1/commands/STOP_SESSION/
    → StopCommandServices.stop_session()
    → Webhook to charge point → charge point stops
    → stop_transaction fires → CDR created as normal
```

---

## Hubject routing branch

Triggered when `authorization.responding_party == HUBJECT_OPERATOR_ID`.

- `session.hub_session_id` set (Hubject's UUID — used in all OICP calls)
- `session.route_through_oicp = True`
- Session updates **do not go to MSP via OCPI**; instead:

| Event | Sent to Hubject as |
|---|---|
| start_transaction | ChargingNotificationStart |
| meter_values | ChargingNotificationProgress (skipped if energy = 0) |
| stop_transaction | ChargingNotificationEnd + eRoamingChargeDetailRecord |

See `hubject-integration` skill for OICP field details.

---

## CDR creation conditions

Created inside `stop_and_create_cdr()` in a single atomic DB transaction.

**Skipped (with error log) if:**
- `session.connector` is `None`
- `session.total_cost_excl_vat` is `None`

`get_or_create_cdr()` is idempotent — safe to call twice, produces one CDR per session.

After creation:
- Normal flow → POST CDR to MSP
- Hubject flow → `HubjectService.post_eroaming_charge_detail_record()`

---

## auth_method — set once at create_session(), never changed

| Value | Set when |
|---|---|
| `WHITELIST` | Token `whitelist=ALWAYS` — no MSP call made |
| `AUTH_REQUEST` | MSP responded to real-time auth request |
| `COMMAND` | Session created via MSP `START_SESSION` command |

---

## Token type → authorization behaviour

| token.type | In DB | MSP call | auth_method |
|---|---|---|---|
| `RFID` | Yes | Only if not whitelisted | `WHITELIST` or `AUTH_REQUEST` |
| `APP_USER` | No | Broadcast, first ALLOWED wins | `AUTH_REQUEST` |
| `AD_HOC_USER` | No | Broadcast, cached 15 min on repeat tap | `AUTH_REQUEST` |
