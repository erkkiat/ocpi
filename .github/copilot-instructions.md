# OCPI Connector - AI Coding Agent Guide

## Project Overview

This is a Django-based **EV charging roaming connector** that bridges CPO (Charge Point Operators) and MSP (e-Mobility Service Providers) using OCPI 2.2 and OICP protocols. The system handles real-time authorization, session management, metering, and billing for EV charging networks.

**Key Technologies**: Django 4.2, Celery, Redis, PostgreSQL, MQTT (Paho), Pydantic, django-ninja

## Architecture Deep Dive

### Three-Layer Separation (CRITICAL)
```
models.py          → Database models ONLY (no business logic)
services/          → Pure business logic (no DB access)
repositories/      → Database interface layer (get_*, create_*, update_*)
serializers/schemas/ → Pydantic/DRF validation
api/               → django-ninja endpoints (prefer over DRF for new code)
```

**Example**: [ocpi22/locations/services.py](ocpi22/locations/services.py) uses `LocationRepository` from [ocpi22/commands/repository.py](ocpi22/commands/repository.py) to access DB, never direct ORM calls.

### MQTT Message Flow (Core Feature)
1. **Charging Station** → MQTT topics (meter values, status, auth requests)
2. **MQTT Subscriber** ([ocpi22/cpo/mqtt/mqtt_subscriber.py](ocpi22/cpo/mqtt/mqtt_subscriber.py)) → Singleton client listens
3. **Handler** ([ocpi22/cpo/mqtt/mqtt_handler.py](ocpi22/cpo/mqtt/mqtt_handler.py)) → Routes by topic
4. **Celery Tasks** ([ocpi22/cpo/mqtt/tasks.py](ocpi22/cpo/mqtt/tasks.py)) → Process async with `@shared_task(queue="HIGH")`
5. **Services** ([ocpi22/cpo/mqtt/services.py](ocpi22/cpo/mqtt/services.py)) → Authorize tokens, create sessions
6. **Publisher** ([ocpi22/cpo/mqtt/mqtt_publisher.py](ocpi22/cpo/mqtt/mqtt_publisher.py)) → Send auth responses back

**Environment variables**: `SMAPPEE_AUTH_REQUEST_TOPIC`, `SMAPPEE_METER_VALUES_TOPIC`, `ENABLE_MQTT_AUTHORIZE`

### OCPI Protocol Integration
- **Credentials Exchange**: [ocpi22/credentials/](ocpi22/credentials/) handles party registration
- **Routing**: [ocpi22/routing.py](ocpi22/routing.py) - `find_route_from_credentials()` determines which MSP to forward requests
- **Sessions**: CPO creates sessions via [ocpi22/sessions/util.py](ocpi22/sessions/util.py) `create_session()`, MSPs query via [ocpi22/msp/api.py](ocpi22/msp/api.py)
- **CDRs**: Charge Detail Records generated in [ocpi22/models/cdr.py](ocpi22/models/cdr.py), sent via [ocpi22/tasks.py](ocpi22/tasks.py) `send_ocpi_request()`

### Celery Task Patterns
```python
# Use orjson serialization (configured in tasks.py)
@shared_task(queue="HIGH", max_retries=3, retry_backoff=60)
def process_authorization_request(data):
    # Always use RefreshTokenBaseTask for long-running tasks
    # See base_task_services.py
```

**Queues**: `HIGH` (auth/realtime), `default` (background), configured in [ocpi22/cpo/mqtt/tasks.py](ocpi22/cpo/mqtt/tasks.py) `CeleryConfig`

## Development Workflows

### Run Project Locally
```bash
docker-compose -f docker-composes/docker-compose.dev.yml up  # Postgres, Redis, MQTT broker
python manage.py runserver  # After creating .env from .env.example
```

### Testing Commands (STRICT RULES BELOW)
```bash
pytest                          # All tests
pytest path/to/test.py::TestClass::test_method -v  # Single test
pytest -k "test_name_pattern"   # By name pattern
./coverage.sh                   # Coverage report (min 69%)
```

### Code Quality
```bash
ruff format          # Auto-format (Black style, 88 char lines)
ruff check           # Lint
pre-commit install   # Auto-runs on commit (format, lint, migration check)
```

## Testing Philosophy (NON-NEGOTIABLE)

### What to Mock ✅
- External HTTP APIs (OCPI party endpoints, Hubject)
- Email sending (`django.core.mail`)
- Celery `.delay()` calls in **unit tests only** (use `task_always_eager=True` in integration)
- Time (`time_machine` library for freezing time)
- MQTT publish in unit tests (`@patch("ocpi22.cpo.mqtt.mqtt_client.MQTTClientSingleton")`)

### What NEVER to Mock ❌
- Django ORM/models in integration tests
- Business logic functions (services/)
- Pydantic schema validation
- Celery task function bodies (test the actual implementation)
- Django views/serializers (test the full request/response cycle)
- Redis operations in integration tests

### Test Organization
- **Unit tests**: [webhooks/tests/test_services.py](webhooks/tests/test_services.py) - Mock DB, test logic
- **Integration tests**: [ocpi22/locations/test_location_services.py](ocpi22/locations/test_location_services.py) - Real DB via `@pytest.mark.django_db`
- **Fixtures**: Centralized in [conftest.py](conftest.py), use factories from [ocpi22/tests/factories.py](ocpi22/tests/factories.py)

**Example**: See [ocpi22/cpo/mqtt/tests/test_mqtt_publisher.py](ocpi22/cpo/mqtt/tests/test_mqtt_publisher.py) for proper MQTT mocking patterns.

## Project-Specific Conventions

### String Formatting
Use **double quotes** everywhere (enforced by ruff):
```python
logger.info(f"Processing session {session.uid}")  # ✅
logger.info(f'Processing session {session.uid}')  # ❌
```

### Type Hints (REQUIRED for all new code)
**Strict typing is mandatory for all new functions, classes, and methods:**
```python
from typing import Optional, List, Dict
from django.http import HttpRequest, JsonResponse

# ✅ Good - Full type annotations
def get_session_by_uid(session_uid: str) -> Optional[Session]:
    try:
        return Session.objects.get(uid=session_uid)
    except Session.DoesNotExist:
        return None

# ✅ Good - Typed service method
class SessionService:
    def create_session(
        self, 
        token: str, 
        location_id: str,
        evse_id: str
    ) -> Session:
        # Implementation
        pass

# ❌ Bad - Missing type hints
def process_data(data):
    return transform(data)
```

**Type checking:**
- Run `mypy --config-file=mypy.ini <file>` before committing
- Pre-commit hooks enforce type checking
- CI provides type checking reports

**Django-specific types:**
```python
from typing import QuerySet
from django.db.models import Q

def get_active_sessions(country: str) -> QuerySet[Session]:
    return Session.objects.filter(status="ACTIVE", country=country)
```

See [mypy.ini](mypy.ini) for complete configuration.

### API Development
**Prefer django-ninja** for new APIs (see [custom_ninja_api.py](custom_ninja_api.py)):
```python
from custom_ninja_api import CustomNinjaAPI
api = CustomNinjaAPI(urls_namespace="locations")

@api.put("/locations/{location_id}", auth=NinjaBasicAuth())
def update_location(request, location_id: str, data: LocationIn):
    # Validates with Pydantic, auto-generates OpenAPI docs
```

**Legacy DRF**: [ocpi22/cpo/api.py](ocpi22/cpo/api.py) uses ViewSets - maintain but don't expand.

### Database Access Patterns
Always use repositories:
```python
# ❌ Direct ORM in services
session = Session.objects.get(uid=session_id)

# ✅ Repository pattern
from ocpi22.commands.repository import SessionRepository
session = SessionRepository().get_session_by_uid(session_id)
```

### Error Handling in MQTT
Never crash the subscriber - log and continue:
```python
def on_message(client, userdata, message):
    try:
        process_data(message)
    except Exception:
        logger.error("Processing failed - subscriber continues", exc_info=True)
        return  # DON'T raise
```

## Critical File Reference

| Purpose | File |
|---------|------|
| MQTT client singleton | [ocpi22/cpo/mqtt/mqtt_client.py](ocpi22/cpo/mqtt/mqtt_client.py) |
| Token authorization logic | [ocpi22/tokens/auth.py](ocpi22/tokens/auth.py) |
| Session creation | [ocpi22/sessions/util.py](ocpi22/sessions/util.py) |
| OCPI routing | [ocpi22/routing.py](ocpi22/routing.py) |
| Celery config | [ocpi22/cpo/mqtt/tasks.py](ocpi22/cpo/mqtt/tasks.py) |
| Test factories | [ocpi22/tests/factories.py](ocpi22/tests/factories.py) |
| Settings (dev/test/prod) | [ocpiconnector/settings/](ocpiconnector/settings/) |

## Context Generation System

**Before starting work**, run:
```bash
make claude-context  # Generates .claude_context_auto.md with git status, structure
```

Then reference `.claude_context.md` and `.claude_context_auto.md` for full architectural understanding. See [.claude/README.md](.claude/README.md) for 32 predefined code flow groups.

## Common Pitfalls

1. **Don't** use `import django; django.setup()` in non-task files (it's in [ocpi22/cpo/mqtt/tasks.py](ocpi22/cpo/mqtt/tasks.py) for Celery only)
2. **Don't** forget to set `DJANGO_SETTINGS_MODULE=ocpiconnector.settings.dev` in environment
3. **Don't** mock `Session.objects` in integration tests - use real DB via `@pytest.mark.django_db`
4. **Don't** use single quotes for strings (ruff will fail)
5. **Don't** add business logic to `models.py` - use `services/` instead

## Key Insights from Existing Code

- **Session caching**: Redis used for high-frequency lookups ([ocpi22/cpo/session_cache.py](ocpi22/cpo/session_cache.py))
- **Party identification**: `Party` dataclass in [ocpiconnector/party.py](ocpiconnector/party.py) represents OCPI parties (country_code + party_id)
- **Multiple environments**: Heroku deployment with separate settings ([ocpiconnector/settings/production.py](ocpiconnector/settings/production.py))
- **Hubject integration**: OICP protocol converter in [integrations/hubject/](integrations/hubject/)

---

**For detailed testing matrix, domain design patterns, and complete architectural flows, see [CLAUDE.md](CLAUDE.md) and [.claude/README.md](.claude/README.md).**
