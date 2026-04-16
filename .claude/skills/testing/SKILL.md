---
name: testing
description: >
  Comprehensive testing guidelines for ocpiconnector. Covers test types and
  preference order, what to mock (and what never to mock), stack-specific rules
  for Django views, Celery tasks, MQTT, Redis, and DB, test naming conventions
  with examples, determinism rules, assertion patterns, fixture organisation,
  mocking style, log assertions, exception coverage, and API test patterns.
  Load this skill for ANY task involving writing, reviewing, or generating tests.
---

# ocpiconnector Testing Guidelines

## Test Types and Preference

- **Unit tests**: test logic of a single function or class with no I/O; only outbound HTTP calls are mocked. Prefer for pure logic — validators, formatters, calculators.
- **Integration tests**: test components together with real DB, Redis, and MQTT broker; only outbound HTTP calls are mocked. **Prefer over unit tests** when the function touches the DB, cache, or message queue.
- **E2E tests**: full system running with all real infrastructure; minimal to no mocks.

**When in doubt, write an integration test.**

**Test Settings**: `ocpiconnector/settings/tests.py`
**Fixtures**: `conftest.py` files at various levels

---

## What to Mock

The only thing that should be mocked in **any** test type is outbound HTTP calls — external OCPI partners, Hubject, and any third-party API. Everything else runs real.

✅ **Always mock** (in all test types):
- Outbound HTTP calls to external APIs (OCPI parties, Hubject, any third-party)
- Email sending

✅ **Mock in unit tests only** (run real in integration/E2E):
- Time and randomness (`timezone.now()`, `uuid`, `random`) — use `time_machine` to freeze, not mock
- MQTT messages — simulate in unit tests, real broker in integration/E2E
- Celery `.delay()` / `.apply_async()` — when testing the caller, not the task itself

❌ **Never mock** (in any test type):
- Core business logic
- Django ORM / DB interactions — use real test DB always
- Redis — use real Redis always
- Celery task bodies — test task logic for real
- Django views and serializers — use Django test client
- Middleware and request lifecycle
- Message decoding schemas (`TokenAuthorizationSchema`, etc.)

---

## Stack-Specific Guidelines

**Django views/APIs:**
- Use pytest Django test client for all view/API tests
- Always use real test DB — never mock ORM
- Always assert both `response.status_code` and full `response.json()` body

**Celery tasks:**
- Mock `.delay()` / `.apply_async()` calls in unit tests when testing the caller
- Never mock the task body — test task logic for real always
- Use `CELERY_TASK_ALWAYS_EAGER=True` or call `.run()` directly to test task bodies
- Mock outbound HTTP calls inside the task, nothing else

**MQTT subscriber:**
- Unit test: simulate MQTT messages
- Integration/E2E: run real EMQX broker (Testcontainers or Docker)
- Never mock decoding or processing logic

**Database:**
- Always use real Postgres test DB — in unit, integration, and E2E

**Redis:**
- Always use real Redis — in unit, integration, and E2E

**Environment variables:**
- Use `monkeypatch.setenv` / `monkeypatch.delenv`
- Use `override_settings` from Django for settings-level overrides

---

## Test Matrix

| Component       | Unit Test                        | Integration Test   | E2E Test            |
|----------------|----------------------------------|--------------------|---------------------|
| External API   | ✅ Mock                          | ✅ Mock            | ❌ Optional mock    |
| Postgres DB    | ✅ Real DB                       | ✅ Real DB         | ✅ Real DB          |
| Redis          | ✅ Real Redis                    | ✅ Real Redis      | ✅ Real Redis       |
| MQTT Broker    | ✅ Simulate msgs                 | ✅ Real broker     | ✅ Real broker      |
| Celery Tasks   | ✅ Mock .delay(), real task body | ✅ Real (eager)    | ✅ Real workers     |
| Django Views   | ✅ pytest client                 | ✅ pytest client   | ✅ HTTP request     |
| Business Logic | ❌ Never mock                    | ❌ Never mock      | ❌ Never mock       |

---

## Test Naming Convention

**Pattern:** `test_<function_or_method>_<condition>_<expected_outcome>`

The name must fully describe intent — no comments needed inside the test.

**Naming rules:**
- The outcome must state the **exact observable result** — never vague quality words like `correctly`, `properly`, `successfully`, `works`, `handles`, `behaves`
- Instead of `correctly`, name what the value actually is: `returns_100`, `sets_status_to_completed`, `subtracts_start_kwh_from_stop_kwh`
- Instead of `successfully`, name what success looks like: `returns_201_with_terminal_data`, `persists_fac_to_database`
- Instead of `handles`, name the specific outcome: `returns_none`, `raises_value_error`, `skips_send_updates`
- The condition must be concrete: not `with_valid_data` but `when_stop_kwh_exceeds_start_kwh` or `when_session_is_active`

**❌ Vague (never do):**
```
test_stop_transaction_post_calculates_total_kwh_correctly
test_authorize_handles_token_properly
test_meter_values_processing_works_when_session_active
test_evse_status_update_behaves_correctly_on_duplicate
```

**✅ Specific (always do):**
```
test_stop_transaction_post_returns_total_kwh_as_stop_kwh_minus_start_kwh
test_authorize_returns_not_allowed_when_token_whitelist_is_never
test_process_meter_values_exits_early_when_session_status_is_pending
test_save_and_send_evse_status_updates_skips_send_when_status_unchanged
```

**General/service/task examples:**
```
test_connect_client_max_retries_exceeded_raises
test_process_meter_values_data_exits_early_if_decode_message_fails
test_process_meter_values_update_fails_when_celery_kwargs_not_satisfied
test_process_status_update_data_returns_none_when_data_validation_fails
test_format_evse_id_returns_country_party_and_uid_joined_with_asterisks
test_get_country_and_party_id_raises_value_error_when_cpo_not_set
test_save_and_send_evse_status_updates_exits_gracefully_when_evse_not_found
test_update_meter_values_async_skips_processing_when_session_not_active
test_on_message_does_not_call_authorize_when_auth_topic_not_matched
test_on_message_mqtt_authorize_missing_env_var_defaults_to_disabled
```

**API test examples (chargepoint-style DRF, no OCPI envelope):**
```
test_status_change_post_forbidden_for_authenticated_user
test_status_change_post_with_non_existing_evse_return_400
test_status_change_post_with_invalid_status_return_400
test_authorize_post_returns_200_with_allowed_token
test_authorize_with_never_token_unauthorized
test_start_transaction_post_creates_session_and_returns_200
test_stop_transaction_post_with_unauthenticated_client_return_401
test_stop_transaction_post_with_completed_session_returns_409
test_stop_transaction_post_returns_total_kwh_as_stop_kwh_minus_start_kwh
test_stop_transaction_get_returns_400
```

**API test examples (OCPI protocol-style with OCPI envelope):**
```
test_post_terminal_creates_terminal_and_returns_201
test_post_terminal_duplicate_returns_400
test_post_terminal_without_auth_returns_401
test_post_terminal_with_cpo_role_returns_400
test_post_terminal_with_invalid_coordinates_returns_400
test_get_terminal_returns_404_when_terminal_belongs_to_different_party
test_list_terminals_returns_only_terminals_for_authenticated_party
test_post_fac_links_terminal_when_terminal_id_provided
test_post_fac_returns_400_when_terminal_belongs_to_different_party
test_get_fac_response_has_nested_total_costs_with_currency_at_root
test_list_facs_returns_200_with_empty_list
```

---

## Test Generation Rules

### Determinism (mandatory)
- Always freeze time with `time_machine.travel("YYYY-MM-DD HH:MM:SS", tick=False)` — never patch `timezone.now` directly
- `tick=False` is mandatory — ticking clocks break determinism
- The frozen timestamp must match any timestamp strings passed as arguments in the same test
- Use `factory.Sequence` for fields that must be unique across tests (e.g. `terminal_id`, `fac_id`)
- Use `factory.LazyFunction` / `factory.LazyAttribute` for values computed at creation time
- Fixed datetimes in factories for deterministic assertions are fine: `datetime(2025, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("UTC"))`
- Never hardcode PKs or UUIDs in test bodies — let factories generate them, then reference via `obj.pk` / `obj.uid`

### Structure rules (no exceptions)
- No `if`, `for`, `while`, `try/except` in test bodies
- No `isinstance()` or `len()` checks — assert exact values
- No string interpolation to build expected values — compute separately before asserting
- Parametrize when testing the same logic with different inputs — not to combine unrelated scenarios
- Each parametrized case must be independently meaningful — no padding with redundant cases
- When parametrizing status values, use real model constants (`Session.ACTIVE`, `Session.PENDING`) — never raw strings

### Assertions
- Always assert **both** `response.status_code` and the **full** `response.json()` body for API tests
- For OCPI envelope responses always assert: `status_code`, `status_message` (or its absence on lists), `timestamp` presence, and the full `data` payload
- For write operations: assert both the state change (DB) and the side effect (mock call)
- For early-exit paths: assert return value AND that downstream calls were not made
- Never assert only on mock call counts — also assert the arguments passed
- Multiple asserts per test are fine when they belong to the same scenario — do not mix scenarios

### Fixtures and conftest.py organisation
- Always use factories for DB objects — never call `Model.objects.create()` directly
- Keep fixtures at the narrowest scope possible — method-level unless shared across a full class
- Never put assertions inside fixtures
- Teardown only when objects are created outside Django's `@pytest.mark.django_db` transaction rollback
- Only add `@pytest.mark.django_db` when the test actually touches the DB — not preemptively

**conftest.py placement rules:**
- Root `conftest.py` — project-wide fixtures only: Django client variants (`admin_user_client`, `authenticated_user_client`), shared credentials, global autouse fixtures
- App-level `conftest.py` (e.g. `ocpi22/conftest.py`) — fixtures shared across that app's test modules
- Module-level `conftest.py` (e.g. `ocpi22/payments/tests/conftest.py`) — fixtures specific to that test module only
- Never define a fixture in a higher-level conftest if it's only used in one test file — define it in that file or its local conftest
- Never duplicate fixtures across conftest files — if it's needed in two places, move it up one level

### Mocking style
- Patch at the **point of use**, not the point of definition
  - ✅ `ocpi22.cpo.mqtt.mqtt_handler.process_authorize_data`
  - ❌ `ocpi22.cpo.mqtt.tasks.process_authorize_data`
- Prefer `monkeypatch.setattr` over `patch` for service-layer method substitution
- Use `patch.object(instance, 'method')` only when asserting on a specific instance's method call

### Log assertions
- Assert on `caplog.text` or `caplog.records` — never on print output
- Always set `caplog.set_level("INFO"/"WARNING", logger="<specific_logger>")` — never rely on root logger
- Assert on exact message substrings, not regex, unless the message contains dynamic content
- For dynamic content: `any(... in record.message for record in caplog.records)`

### Exception coverage
- Every function that catches exceptions must have: happy path test AND exception path test
- Exception tests must assert: (a) correct log message emitted, (b) no side effects (mocks not called), (c) expected return value

---

## API Test Patterns

**DRF chargepoint-style (no OCPI envelope):**
```python
def test_stop_transaction_post_with_completed_session_returns_409(
    self, admin_user_client, session
):
    session.status = "COMPLETED"
    session.save()
    request_body = {"session_id": session.uid, "stop_kwh": 100}

    response = admin_user_client.post(self.stop_transaction_url, data=request_body)

    assert response.status_code == 409
    assert response.json() == {
        "status_text": "Session was completed earlier, cannot stop it twice"
    }
```

**OCPI protocol-style (with OCPI envelope):**
```python
def test_post_terminal_creates_terminal_and_returns_201(
    self, client, ptp_credentialsrole, ocpi_headers, valid_terminal_data
):
    response = client.post(
        f"{TERMINALS_URL}/", data=valid_terminal_data, format="json", **ocpi_headers
    )

    body = response.json()
    assert response.status_code == status.HTTP_201_CREATED
    assert body == {
        "status_code": 1000,
        "status_message": "Success",
        "timestamp": body["timestamp"],
        "data": {
            "terminal_id": "TERM-API-001",
            "customer_reference": "TEST-CUSTOMER-REF",
            "location_ids": [],
            "evse_uids": [],
            "last_updated": body["data"]["last_updated"],
        },
    }
    assert Terminal.objects.filter(terminal_id="TERM-API-001").exists()
```

**Note on dynamic fields:** For fields that are inherently dynamic (`timestamp`, `last_updated`, UUIDs), assign `body = response.json()` first, then echo those fields back in the expected dict. This keeps a single `==` assertion while still verifying the full structure and all static fields.

**Auth/permission coverage per endpoint (mandatory):**
Every endpoint must have dedicated tests for:
- `401` — unauthenticated request
- `403` — authenticated but wrong role/permission (DRF-style endpoints)
- `400` — invalid input (parametrize field validation cases where applicable)
- `404` — resource not found or belongs to a different party
- `200`/`201` — happy path with full body assertion

---

## Testing Anti-Patterns (DO NOT DO)

❌ **Never do in test bodies**:
- `if`, `for`, `while`, `try/except` blocks
- `isinstance()` or `len()` checks
- Asserting only mock call counts without asserting arguments
- Asserting only `status_code` without asserting `response.json()` body
- Calling `response.json()` multiple times inline — assign to `body` first

❌ **Never mock** (see What to Mock above for full rules):
- Django ORM, Redis, task bodies, views, schemas, business logic
