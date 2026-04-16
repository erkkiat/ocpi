# CLAUDE.md - Guide for Agentic Coding in OCPI Connector

## 🚀 Quick Start

Before starting any work session, regenerate fresh context:

```bash
make claude-context
```

Context is **automatically injected** at the start of every Claude session via a `SessionStart` hook — no need to ask Claude to read the files manually.

The context is also **auto-regenerated** whenever you switch or create a branch (via `.githooks/post-checkout`).

This gives Claude instant understanding of:
- Complete project architecture
- Recent git changes and current state
- All 32 code flows and their relationships
- Your strict testing preferences

### First-time local setup

To activate the branch hook, run once after cloning:

```bash
git config core.hooksPath .githooks
pre-commit install
```

**📚 For complete documentation, see:**
- [.claude/README.md](.claude/README.md) - System overview
- [.claude/docs/CLAUDE_QUICK_START.md](.claude/docs/CLAUDE_QUICK_START.md) - Quick reference
- [.claude/docs/CLAUDE_CONTEXT_README.md](.claude/docs/CLAUDE_CONTEXT_README.md) - Full guide

---

## Skills (ALWAYS load before writing code)

Skills live in `.claude/skills/`. They work alongside context files — context gives
project state, skills give reference knowledge. Load the relevant skill(s) before
any code task.

| Skill | When to load |
|---|---|
| `.claude/skills/ocpiconnector-standards/SKILL.md` | **Every code task** — naming, serializer patterns, anti-patterns, test rules, terminal rules, API framework |
| `.claude/skills/testing/SKILL.md` | **Any task writing or reviewing tests** — mock rules, naming, determinism, assertions, fixtures, API patterns |
| `.claude/skills/ocpi-spec/SKILL.md` | Any task touching credentials, tokens, sessions, CDRs, locations, commands, hub routing |
| `.claude/skills/directpayment-spec/SKILL.md` | Any task touching `ocpi22/payments/` — Terminal, FAC, PTP role, wire format |

### Terminal rules
- Terminal is already at project root — **never `cd ocpiconnector`**
- **Always pass `projectPath: ~/ocpiconnector`** to every JetBrains tool call
- **Always use `executeInShell: true`** and prefix commands with `source .venv/bin/activate &&`
- **Never use `2>/dev/null`** — JetBrains terminal does not support POSIX redirects
- Prefer `bash_tool` for file reads/greps; use JetBrains terminal for pytest/Docker/manage.py
- Prefer `bash_tool` for file reads/greps; use JetBrains terminal for pytest/Docker/manage.py

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

### Typing Requirements (NEW - Required for all new code)

**All new code MUST include explicit type hints:**
- Function/method signatures with parameter types and return types
- Class attributes and instance variables
- Module-level variables

**Type checking tool: MyPy with django-stubs**
```bash
mypy --config-file=mypy.ini <file_or_directory>
```

**Examples of proper typing:**
```python
from typing import Optional, List, Dict, Any
from django.http import HttpRequest, HttpResponse
from ocpi22.models import Session, Location

# ✅ Good - All parameters and return types annotated
def get_session_by_uid(session_uid: str) -> Optional[Session]:
    """Retrieve a session by its UID."""
    try:
        return Session.objects.get(uid=session_uid)
    except Session.DoesNotExist:
        return None

# ✅ Good - Service class with typed methods
class LocationService:
    def __init__(self, repository: LocationRepository) -> None:
        self.repository = repository
    
    def create_location(
        self, 
        name: str, 
        address: str, 
        coordinates: Dict[str, float]
    ) -> Location:
        """Create a new location with validation."""
        location = self.repository.create(
            name=name,
            address=address,
            latitude=coordinates["latitude"],
            longitude=coordinates["longitude"]
        )
        return location

# ❌ Bad - No type hints
def process_data(data):
    result = transform(data)
    return result
```

**Django-specific typing patterns:**
```python
from typing import Optional, List, QuerySet
from django.db.models import Q
from django.http import HttpRequest, JsonResponse

# QuerySet typing
def get_active_locations(country: str) -> QuerySet[Location]:
    return Location.objects.filter(country=country, publish=True)

# Request/Response typing
def location_list_view(request: HttpRequest) -> JsonResponse:
    locations = get_active_locations(request.GET.get("country", "BE"))
    return JsonResponse({"locations": list(locations.values())})
```

**Pre-commit and CI:**
- Pre-commit hook runs mypy on changed files
- CI workflow provides type checking report (informational only)
- Fix type errors in new code before merging

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

## Testing Guidelines

See **`.claude/skills/ocpiconnector-standards/SKILL.md`** — the "Testing rules (strict)" section is the single source of truth for test structure, naming, mock boundaries, parametrize rules, and the `OCPIAPIRequestFactory` pattern.

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
make claude-context   # regenerate if not on a fresh branch
```
Then in Claude:
```
"Read .claude/skills/ocpiconnector-standards/SKILL.md"
"I need to add a new MQTT message type for remote diagnostics. Guide me."
```

### 2. Working on payments/DirectPayment
```
"Read .claude/skills/ocpiconnector-standards/SKILL.md"
"Read .claude/skills/directpayment-spec/SKILL.md"
```

### 3. Debugging OCPI protocol issues
```
"Read .claude/skills/ocpi-spec/SKILL.md"
```

### 4. Generating Tests
```
"Read .claude/skills/ocpiconnector-standards/SKILL.md"
"Read .claude/skills/testing/SKILL.md"
"Read ocpi22/cpo/mqtt/tasks.py"
"Generate unit tests for process_authorization_request following my test preferences"
```

### 5. Debugging Issues
```
"What changed recently?" (context is already loaded)
"The authorization flow is failing. Based on recent changes, what might be wrong?"
```

---

## Key Reminders for Claude

1. **Always load `ocpiconnector-standards` skill** before writing any code
2. **Context is auto-loaded** at session start — run `make claude-context` manually only when starting work on a new branch without switching (context auto-regenerates on branch switch)
3. **Use flows** instead of reading entire modules
4. **Follow test preferences** strictly — load `.claude/skills/testing/SKILL.md` for any test task
5. **Never mock business logic** - only mock boundaries
6. **Use real DB/Redis/MQTT** in integration tests
7. **Parametrize tests** - no ifs/loops in test code
8. **Clear test names** that describe intention (no comments needed)
9. **Never `cd ocpiconnector`** - terminal is already at project root
10. **Never use `&&` or `2>/dev/null`** in JetBrains terminal

---

**For questions or issues with the Claude context system, see [.claude/README.md](.claude/README.md)**
