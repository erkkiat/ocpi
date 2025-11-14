# OCPI Connector - Claude Context Guide

## Project Overview
OCPI Connector is a Django-based platform for managing electric vehicle charging infrastructure using the OCPI (Open Charge Point Interface) protocol v2.2.1. The system integrates with charge points via MQTT and provides roaming capabilities for EV charging networks.

## Technology Stack
- **Framework**: Django 4.x with Django Ninja for API
- **Task Queue**: Celery with Redis broker (2 workers, separate queues)
- **Message Protocol**: MQTT (EMQX broker) for charge point communication
- **Database**: PostgreSQL via Django ORM
- **Cache**: Redis (Celery broker + caching)
- **Infrastructure**: Docker containers
- **Testing**: pytest with pytest-django
- **External APIs**: OCPI v2.2.1, Hubject/OICP integration

## Project Structure

### Core Apps
- `ocpi22/` - Main OCPI implementation
  - `cpo/` - Charge Point Operator functionality
    - `mqtt/` - MQTT subscriber, publisher, handlers, tasks
    - `schemas.py` - Pydantic schemas for CPO messages
    - `services.py` - Business logic for charge point operations
    - `api.py` - CPO API endpoints
    - `session_service.py` - Session management logic
    - `session_cache.py` - Redis-based session caching
  - `msp/` - Mobility Service Provider functionality
  - `ocpi/` - Core OCPI protocol implementation
  - `tokens/` - Token authorization handling
  - `commands/` - Remote command handling (START_SESSION, STOP_SESSION, etc.)
  - `locations/` - Location/EVSE management
  - `sessions/` - Session tracking
  - `models/` - Django ORM models for OCPI entities
  - `tasks.py` - Celery tasks for OCPI operations

- `ocpiconnector/` - Django project settings
  - `settings/` - Environment-specific settings (dev, staging, production, tests)
  
- `integrations/` - External integrations
  - `hubject/` - Hubject/OICP protocol conversion

- `payment/` - Payment processing
- `settlement/` - Settlement and invoicing

### Testing Structure
- `tests/` - Root test directory
  - `unit/` - Unit tests
  - `integration/` - Integration tests
- `ocpi22/tests/` - OCPI-specific tests
- `ocpi22/cpo/tests/` - CPO-specific tests
- `ocpi22/cpo/mqtt/tests/` - MQTT-specific tests

## Key Data Flows

### 1. Authorization Flow (MQTT → OCPI)
```
Charge Point → MQTT Message → mqtt_subscriber.py → TokenAuthorizationSchema (validation)
→ authorization service → OCPI Token validation → Celery task (external OCPI API call)
→ Authorization result → Response to charge point
```

**Key Files:**
- `ocpi22/cpo/mqtt/mqtt_subscriber.py` - Receives MQTT messages
- `ocpi22/cpo/mqtt/schemas.py` - TokenAuthorizationSchema, StatusUpdateSchema, MeterValuesSchema
- `ocpi22/cpo/mqtt/tasks.py` - process_authorization_request, process_status_update, process_meter_values
- `ocpi22/tokens/auth.py` - Token validation logic
- `ocpi22/tasks.py` - OCPI API communication tasks

### 2. Session Management Flow
```
MQTT Status Update → mqtt_handler.py → StatusUpdateSchema → session_service.py
→ Session creation/update in DB → session_cache.py (Redis) → CDR generation
```

**Key Files:**
- `ocpi22/cpo/session_service.py` - Session lifecycle management
- `ocpi22/cpo/session_cache.py` - Redis caching for active sessions
- `ocpi22/models/session.py` - Session ORM model
- `ocpi22/models/cdr.py` - Charge Detail Record model

### 3. Meter Values Flow
```
MQTT Meter Values → mqtt_handler.py → MeterValuesSchema → meter service
→ Update session energy/costs → Cache update → Database update
```

**Key Files:**
- `ocpi22/cpo/mqtt/tasks.py` - process_meter_values task
- `ocpi22/cpo/services.py` - Meter value processing logic

### 4. Remote Commands Flow (CPO API → Charge Point)
```
OCPI Remote Command → command service → Celery task → MQTT publisher
→ Charge point receives command → Status callback → Command result
```

**Key Files:**
- `ocpi22/commands/services.py` - Command handling logic
- `ocpi22/commands/api.py` - Command API endpoints
- `ocpi22/cpo/mqtt/mqtt_publisher.py` - Publishes to MQTT
- `ocpi22/cpo/mqtt/tasks.py` - Command execution tasks

## External Dependencies

### OCPI v2.2.1 API
- **Purpose**: Inter-operator roaming for EV charging
- **Usage**: Token validation, location sync, CDR exchange
- **Mocked in**: Unit and integration tests
- **Real in**: E2E tests and production

### MQTT Broker (EMQX)
- **Purpose**: Real-time communication with charge points
- **Topics**: Per-chargepoint topics for auth, status, meter values
- **Mocked in**: Unit tests (simulated messages)
- **Real in**: Integration and E2E tests (Testcontainers/Docker)

### Charge Point Messages (via MQTT)
Message types handled:
- `TokenAuthorizationSchema` - EV authorization requests
- `StatusUpdateSchema` - Charging session status changes
- `MeterValuesSchema` - Energy consumption updates
- Remote command responses

## Database Models (Django ORM)

### Core Models
- `Token` - Authorization tokens for EVs
- `Session` - Charging sessions
- `CDR` (Charge Detail Record) - Completed session records
- `Location` - Charging station locations
- `EVSE` - Electric Vehicle Supply Equipment
- `Connector` - Physical charging connectors
- `Tariff` / `SolidTariff` - Pricing structures
- `Credentials` / `CredentialsRole` - OCPI partner credentials

**Located in**: `ocpi22/models/`

## Celery Configuration

### Queues
1. **Default Queue**: General background tasks
2. **Priority Queue**: Time-sensitive operations (authorization, commands)

### Key Tasks
- `process_authorization_request` - Handle token authorization
- `process_status_update` - Update session status
- `process_meter_values` - Process energy readings
- `execute_remote_command` - Send commands to charge points
- `sync_locations` - Pull locations from OCPI partners
- `generate_cdr` - Create charge detail records

**Configuration**: `ocpiconnector/celery.py`

## Redis Usage

### 1. Celery Broker
- Task queue management
- Result backend

### 2. Caching
- Session cache (`session_cache.py`)
- EVSE ID lookups
- Token validation cache
- Rate limiting

**Cache Keys**: Prefixed by environment (e.g., `dev:session:`, `prod:evse:`)

## Testing Strategy

### Unit Tests
- **Scope**: Single function/class logic
- **Mocks**: External APIs, MQTT messages, Celery .delay(), time/random, email
- **Real**: Django ORM (test DB), business logic, schemas

### Integration Tests
- **Scope**: Multiple components together
- **Real**: PostgreSQL (test DB), Redis, MQTT broker (Docker), Celery (eager mode)
- **Mocks**: External OCPI APIs, email

### E2E Tests
- **Scope**: Full system
- **Real**: All infrastructure (DB, Redis, MQTT, Celery workers)
- **Minimal Mocks**: Only external partner APIs

**Test Settings**: `ocpiconnector/settings/tests.py`
**Fixtures**: `conftest.py` files at various levels

## Critical Files Reference

### MQTT Subscriber
- `ocpi22/cpo/mqtt/mqtt_subscriber.py` - Main subscriber loop
- `ocpi22/cpo/mqtt/mqtt_handler.py` - Message routing and processing
- `ocpi22/cpo/mqtt/mqtt_client.py` - MQTT client wrapper

### Schemas (Pydantic)
- `ocpi22/cpo/mqtt/schemas.py` - Message validation schemas
- `ocpi22/cpo/schemas.py` - CPO domain schemas

### Services (Business Logic)
- `ocpi22/cpo/services.py` - Core CPO logic
- `ocpi22/cpo/session_service.py` - Session management
- `ocpi22/tokens/auth.py` - Token authorization
- `ocpi22/commands/services.py` - Remote commands

### APIs
- `ocpi22/cpo/api.py` - CPO endpoints (Django Ninja)
- `ocpi22/ocpi/api.py` - Core OCPI endpoints
- `ocpi22/msp/api.py` - MSP endpoints

### Tasks (Celery)
- `ocpi22/cpo/mqtt/tasks.py` - MQTT message processing tasks
- `ocpi22/tasks.py` - OCPI protocol tasks
- `ocpi22/commands/services.py` - Command execution tasks

## Environment Variables

Key configurations (see `.env.example`):
- `DJANGO_SETTINGS_MODULE` - Settings module to use
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Redis connection
- `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` - MQTT broker
- `CELERY_BROKER_URL` - Celery broker
- `OCPI_*` - OCPI partner configurations

## Common Patterns

### 1. MQTT Message Processing
```python
# Pattern used throughout
message = decode_message(payload)  # Pydantic validation
validate_business_rules(message)
result = process_with_service(message)
publish_response_if_needed(result)
```

### 2. OCPI API Calls
```python
# Always done in Celery tasks
@shared_task
def call_ocpi_partner(data):
    response = requests.post(partner_url, json=data, timeout=30)
    response.raise_for_status()
    return response.json()
```

### 3. Session Management
```python
# Pattern: Check cache first, then DB
session = session_cache.get(session_id)
if not session:
    session = Session.objects.get(id=session_id)
    session_cache.set(session_id, session)
```

## Testing Anti-Patterns (DO NOT DO)

❌ **Never mock**:
- Django ORM/models in integration tests
- Pydantic schemas (TokenAuthorizationSchema, etc.)
- Business logic in services
- Django views/serializers

❌ **Never use**:
- `localStorage` or `sessionStorage` in artifacts
- Real OCPI API calls in tests (always mock external APIs)

✅ **Always mock**:
- External OCPI API calls
- Email sending
- Time (`timezone.now()`, `datetime.now()`)
- Random values (`uuid.uuid4()`, `random`)
- Celery `.delay()` in unit tests (but test task logic)

## Git Workflow

- **Main branch**: `main` (production)
- **Staging**: `staging`
- **Development**: `develop`
- **Feature branches**: Branch from and merge to `develop`

## Documentation

- `documentation/` - Feature documentation
  - `authorization.md` - Authorization flow
  - `charging.md` - Charging process
  - `status-change.md` - Session status changes
  - `pricing.md` - Tariff and pricing
  - `invoicing.md` - CDR and invoicing

- `ocpi22/cpo/readme.md` - CPO module overview
- `ocpi22/cpo/mqtt/readme.md` - MQTT implementation details

## Quick Command Reference

```bash
# Run tests
pytest tests/unit/
pytest tests/integration/
pytest ocpi22/tests/

# Run specific test
pytest ocpi22/cpo/mqtt/tests/test_mqtt_handler.py -k test_authorization

# Start services (Docker)
docker-compose -f docker-composes/docker-compose.dev.yml up

# Run Celery worker
celery -A ocpiconnector worker -Q default,priority -l info

# Django management
python manage.py migrate
python manage.py shell
python manage.py test

# Code quality
ruff check .
ruff format .
```

## Notes for AI Assistant

1. **Testing Guidelines**: Strict preferences defined in user preferences - follow them precisely
2. **Never Mock**: Core business logic, schemas, ORM in integration tests
3. **Always Mock**: External APIs, email, time, random in unit tests
4. **MQTT**: Real broker in integration tests, simulated in unit tests
5. **Celery**: Mock `.delay()` in unit tests, use `CELERY_TASK_ALWAYS_EAGER=True` in integration
6. **File Structure**: Tests mirror source structure (e.g., `ocpi22/cpo/services.py` → `ocpi22/cpo/tests/test_services.py`)

---
*Last Updated: 2025-10-13*
*Git Branch: add-call-back-support*
