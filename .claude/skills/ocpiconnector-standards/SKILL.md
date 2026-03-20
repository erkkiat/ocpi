---
name: ocpiconnector-standards
description: >
  Code quality, naming, architecture, and testing standards for the ocpiconnector
  Django/Celery/OCPI project. Load this skill automatically for ANY task involving
  this codebase — writing new code, reviewing code, generating tests, refactoring,
  or debugging. Covers serializer patterns, naming conventions, over-engineering
  anti-patterns, test structure violations, and complexity red flags specific to
  this project. Use it even when the user doesn't say "standards" or "guidelines" —
  if you're touching ocpiconnector code, this skill applies.
---

# ocpiconnector Code Standards

## Terminal usage

The JetBrains/PyCharm terminal is already at the project root.
- **Never** `cd ocpiconnector` or prefix paths with the project name
- **Never** chain commands with `&&` or use `2>/dev/null` — JetBrains terminal does
  not support POSIX redirects; use separate tool calls instead
- Prefer `bash_tool` for file reads, greps, and output inspection; use
  `jetbrains:execute_terminal_command` only for things that require the local
  project environment (running tests, Docker commands, `manage.py`)

Always run commands with the virtualenv activated. Use `executeInShell: true` so
that `source` works in the JetBrains terminal:

```
source .venv/bin/activate && pytest ocpi22/path/to/test.py -v
source .venv/bin/activate && pytest ocpi22/path/to/test.py::test_name -v
source .venv/bin/activate && python manage.py <command>
```

Docker restart (no venv needed):
```
docker-compose -f ./docker-composes/docker-compose.dev.yml restart django-app
```

---

## API framework choice

- **All new non-OCPI endpoints use Django Ninja** — not DRF
- **OCPI protocol endpoints always use DRF** — they must go through the existing OCPI
  request/response pipeline, authentication, and routing middleware
- DRF is only for OCPI endpoints and existing non-OCPI code that already uses it
- Never add a new non-OCPI endpoint in DRF; never put an OCPI endpoint in Ninja

---

## Naming conventions

### Functions and methods
- Names must state **what** the function does, not how: `get_session_by_uid`, not `fetch`
- Verb-noun form: `validate_terminal_party_identification`, not `check_party`
- Boolean predicates: `is_hub`, `has_active_session`, `requires_sender_role`
- Services that call external APIs: prefix with direction —
  `send_ocpi_request`, `pull_objects`, not `do_request`
- Avoid single-letter args except in comprehensions: `creds` → `credentials`,
  `sess` → `session`

### Variables
- Name after what they represent, not the operation: `validated_data` not `result`;
  `partner_credentials` not `creds_obj`
- Loop variables must be meaningful: `for credential in credentials:`, not `for c in ...`

### Test names — strictly follow this pattern:
```
test_<method>_<condition>_<expected_outcome>
```
Examples:
- `test_connect_client_max_retries_exceeded_raises`
- `test_process_meter_values_data_exits_early_if_decode_message_fails`
- `test_authorize_token_invalid_uid_returns_not_allowed`
- `test_terminal_serializer_missing_coordinates_saves_null_lat_lon`

---

## Architecture patterns

### Separation of concerns
```
models/       → DB schema only, no business logic
services/     → business logic, no direct HTTP calls
tasks.py      → Celery tasks; call services, mock external HTTP in tests
serializers/  → wire format only; unpack nested → flat in to_internal_value,
                repack flat → nested in to_representation
api.py        → thin endpoints; delegate to services
```

Never put business logic directly in a view or Celery task body.
Never put HTTP calls directly in a serializer.

### Serializer pattern (canonical — for existing DRF code only)

Use a **single ModelSerializer** per domain object for both read and write.
Nested wire objects (e.g. `GeoLocation`, `Price`) get their own `serializers.Serializer`
subclass used as a write-only nested field.

```python
class GeoLocationSerializer(serializers.Serializer):
    latitude = serializers.CharField(max_length=10, validators=[validate_latitude])
    longitude = serializers.CharField(max_length=11, validators=[validate_longitude])

class TerminalSerializer(serializers.ModelSerializer):
    coordinates = GeoLocationSerializer(required=False, allow_null=True, write_only=True)

    class Meta:
        model = Terminal
        fields = [...]

    def to_internal_value(self, data):
        validated = super().to_internal_value(data)
        if "coordinates" in validated:
            coord = validated.pop("coordinates")
            if coord:
                validated["latitude"] = coord["latitude"]
                validated["longitude"] = coord["longitude"]
        return validated

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.latitude and instance.longitude:
            data["coordinates"] = {"latitude": instance.latitude, "longitude": instance.longitude}
        else:
            data.pop("coordinates", None)
        return data
```

Rules:
- `to_internal_value` → unpack nested → flat model fields. No mutation elsewhere.
- `to_representation` → repack flat → nested wire shape.
- `validate()` → cross-field validation only, no type coercion.
- Never override `create()` or `update()` unless default behaviour is broken.
- Never write separate ReadSerializer and WriteSerializer for the same model.

### When NOT to add a service class
Only create a service class if multiple methods share state or a dependency.
A standalone function is fine for a single operation. Don't wrap a single function
in a class just to look like a service.

---

## Over-engineering red flags

These patterns have been corrected before — avoid them:

| Anti-pattern | Preferred approach |
|---|---|
| Wrapper class around a single function | Module-level function |
| `result = some_func(); return result` | `return some_func()` |
| `AbstractBaseProcessor` with one subclass | Concrete class directly |
| `DataTransferObject` that mirrors the model | Use the model or serializer |
| `process_and_validate_and_save(...)` | Split into focused functions |
| Type aliases for built-in types (`StrId = str`) | Use `str` directly |
| `**kwargs` passthrough in middle of call chain | Explicit parameters |

Ask before adding abstraction: *will there be a second use case this sprint?*
If not, keep it simple.

---

## Complexity limits

- Max function length: ~30 lines. If longer, extract a helper with a clear name.
- Max nesting depth: 3 levels. Flatten with early returns.
- No conditional logic in test code — no `if`, `for`, `while`.
- No `isinstance()` checks in test assertions.
- No `len()` checks — `assert len(result) == 3` → `assert result == [a, b, c]`.

---

## Testing rules (strict)

### Test structure
```python
@pytest.mark.parametrize("input,expected", [
    (valid_case, expected_result),
    (edge_case, edge_result),
])
def test_method_condition_expected_outcome(input, expected):
    result = system_under_test(input)
    assert result.field == expected.field
    assert result.other == expected.other
```

- No comments inside test functions — the name describes intent
- Multiple `assert` statements fine if testing the same outcome
- Never mix outcomes in one test (don't assert success AND error together)
- Always control time: `@pytest.mark.freeze_time` or mock `timezone.now`
- Always control UUIDs: pass explicitly or patch `uuid.uuid4`

### Mock boundaries only
```python
# ✅ Mock the HTTP call, test the task logic for real
@patch("ocpi22.tasks.requests.post")
def test_send_ocpi_request_timeout_raises(mock_post):
    mock_post.side_effect = requests.Timeout()
    with pytest.raises(Retry):
        send_ocpi_request.apply(...)

# ❌ Never mock a service called by the task under test
@patch("ocpi22.cpo.services.SessionService.create_session")
def test_process_status_update_...(mock_service):  # WRONG
```

### Use `OCPIAPIRequestFactory` for API tests
```python
factory = OCPIAPIRequestFactory()
request = factory.put("/ocpi/cpo/2.2.1/sessions/", data, credentials=credentials)
response = view(request)
assert response.status_code == 200
```

### Environment variables in tests
```python
# Django settings → override_settings
@override_settings(PTP_CUSTOMER_REFERENCE="TEST-REF")
def test_...:

# Raw env vars → patch.dict
with patch.dict(os.environ, {"SOME_VAR": "value"}):
    ...
```

---

## Type hints

All new code requires explicit type hints:
```python
# ✅
def get_session_by_uid(session_uid: str) -> Optional[Session]:

# ❌
def get_session(uid):
```

Use `QuerySet[Model]` for ORM return types. Use `Optional[X]` not `X | None` for
Python 3.10 compatibility unless the file already uses `|` union syntax.

---

## Strings and formatting
- Double quotes everywhere (Black-compatible)
- Line length 88 characters
- No f-string in log messages — use `logger.info("msg %s", var)` for lazy evaluation
- Use `ruff format` before committing

---

## OCPI-specific patterns

### Credentials lookup
Always resolve credentials through the cache layer, never raw `Credentials.objects.get`.
Use `find_credentials(token)` from `ocpiconnector.manager`.

### Role resolution for PTP/DirectPayment
For endpoints where the caller is the PTP, `country_code` and `party_id` come from
request headers, not the URL. Use `requires_sender_role(request)` which reads
`OCPI-From-Country-Code` and `OCPI-From-Party-Id` headers.

### `last_updated` on PTP-owned objects
Do NOT use `auto_now=True` on `last_updated` for models owned by the external party
(Terminal, FinancialAdviceConfirmation). The party sets this field; accept it from wire.
Use `auto_now=True` only for fields this system owns.

### Cache invalidation
After any `Credentials` or `CredentialsRole` save/delete, clear:
- `partners_cache`
- `find_credentials`
- `get_credentialsrole`
- `is_hub_cache`
- `find_endpoints_by_roles`
- Redis `_authorize_token` cache
