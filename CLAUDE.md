# CLAUDE.md - Guide for Agentic Coding in OCPI Connector

## 🚀 Quick Start (NEW!)

Before starting any work session, generate fresh context:

```bash
make claude-context
```

Then in Claude chat:
```
"Read .claude_context.md and .claude_context_auto.md"
```

This gives Claude instant understanding of:
- Complete project architecture
- Recent git changes and current state
- All 32 code flows and their relationships
- Your strict testing preferences

**📚 For complete documentation, see:**
- [.claude/README.md](.claude/README.md) - System overview
- [.claude/docs/CLAUDE_QUICK_START.md](.claude/docs/CLAUDE_QUICK_START.md) - Quick reference
- [.claude/docs/CLAUDE_CONTEXT_README.md](.claude/docs/CLAUDE_CONTEXT_README.md) - Full guide

---

## Available Code Flows (32 Total)

Instead of reading hundreds of files, use predefined flows:

```bash
make list-flows                           # See all flows
make claude-flow FLOW=authorization_flow  # Read specific flow
```

**Example flows:**
- `authorization_flow` - Token auth MQTT → OCPI
- `session_management_flow` - Session lifecycle
- `meter_values_flow` - Energy metering
- `payment_system` - Stripe payment processing
- `settlement_reporting` - CDR billing
- `celery_tasks` - All async tasks
- `test_infrastructure` - Test configs

**In Claude, you can say:**
```
"Read the authorization_flow files and explain how token validation works"
```

---

## Build & Test Commands

```bash
# Development
python manage.py runserver           # Run server
pytest                                # Run all tests
pytest path/to/test.py::test_name -v # Run single test

# Code Quality
ruff format                           # Format code
ruff check                            # Lint check
./coverage.sh                         # Test coverage

# Claude Context
make claude-context                   # Regenerate context
make list-flows                       # List available flows
```

---

## Code Style Guidelines

- Follow [Python Anti-Patterns](https://docs.quantifiedcode.com/python-anti-patterns/index)
- Use double quotes for strings (like Black)
- Line length: 88 characters max
- Indent with 4 spaces
- Target Python 3.10 compatibility

---

## Project Structure

```
ocpi22/
├── models.py              # Database models only
├── services/              # Business logic
├── repositories/          # Database interfaces
├── serializers/schemas/   # Data serialization
└── api/                   # API endpoints (django-ninja)
```

**Separation of Concerns:**
- `models.py` - Database models ONLY
- `services/` - Business logic (no DB access)
- `repositories/` - Database interfaces (e.g., get_user_by_id)
- `serializers/schemas/` - Data validation and transformation
- `api/` - API endpoints (use django-ninja for new APIs)

---

## Testing Guidelines (CRITICAL)

### Test Types
- **Unit tests**: Mock external dependencies, test single function/class
- **Integration tests**: Real DB/Redis/MQTT, minimal mocks
- **E2E tests**: Full system, minimal mocks

### What to Mock ✅
- External APIs (OCPI parties, HTTP calls)
- Email sending
- Celery `.delay()` calls (in unit tests only)
- Time and randomness (timezone.now(), uuid, random)
- Filesystem / I/O
- MQTT messages (in unit tests)

### What NOT to Mock ❌
- Business logic
- Django ORM/models (in integration tests)
- Message schemas (TokenAuthorizationSchema, etc.)
- Celery task bodies (test for real)
- Django views and serializers
- Middleware and request lifecycle

### Test Matrix

| Component      | Unit Test        | Integration Test | E2E Test      |
|----------------|------------------|------------------|---------------|
| External API   | ✅ Mock          | ✅ Mock          | ❌ Real/Mock  |
| Postgres DB    | ✅ Optional mock | ✅ Real DB       | ✅ Real DB    |
| Redis          | ✅ Optional mock | ✅ Real Redis    | ✅ Real Redis |
| MQTT Broker    | ✅ Simulate msgs | ✅ Real broker   | ✅ Real broker|
| Celery Tasks   | ✅ Mock .delay() | ✅ Real (eager)  | ✅ Real       |
| Business Logic | ❌ Never mock    | ❌ Never mock    | ❌ Never mock |

**For complete testing guidelines, see `.claude_context.md`**

---

## Pre-commit Workflow

```bash
pre-commit install                    # Install hooks
git commit -m "message"               # Runs checks automatically
```

**Pre-commit checks:**
- Code formatting (ruff)
- Linting (ruff)
- Migration validation (for model changes)

---

## Common Claude Workflows

### 1. Starting a New Feature
```bash
make claude-context
```
Then in Claude:
```
"Read .claude_context.md and .claude_context_auto.md"
"I need to add a new MQTT message type for remote diagnostics. Guide me."
```

### 2. Understanding Existing Code
```bash
make claude-flow FLOW=authorization_flow
```
Then in Claude:
```
"Explain how the authorization_flow works"
```

### 3. Generating Tests
```
"Read .claude_context.md"
"Read ocpi22/cpo/mqtt/tasks.py"
"Generate unit tests for process_authorization_request following my test preferences"
```

### 4. Debugging Issues
```
"Read .claude_context_auto.md - what changed recently?"
"The authorization flow is failing. Based on recent changes, what might be wrong?"
```

---

## Key Reminders for Claude

1. **Always regenerate context** before starting work: `make claude-context`
2. **Use flows** instead of reading entire modules
3. **Follow test preferences** strictly (see `.claude_context.md`)
4. **Never mock business logic** - only mock boundaries
5. **Use real DB/Redis/MQTT** in integration tests
6. **Parametrize tests** - no ifs/loops in test code
7. **Clear test names** that describe intention (no comments needed)

---

## Terminal Context

The PyCharm terminal is already at the project root (`ocpiconnector/`), so you don't need to `cd` into subdirectories when running commands.

```bash
# ✅ Correct
pytest ocpi22/tests/test_auth.py

# ❌ Not needed
cd ocpiconnector
pytest ocpi22/tests/test_auth.py
```

---

**For questions or issues with the Claude context system, see [.claude/README.md](.claude/README.md)**
