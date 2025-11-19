# ocpiconnector

The OCPI Connector provides a simple restful API and some MQTT topics for connecting an existing EV platform
to roaming partners and networks. The API is proprietary and the result of three years of work with
multiple MSPs and CPOs. The API was built on the Open Charge Point Interface (OCPI) standard,
but it accommodates OICP as well.

## Development Setup
* Clone the repository
* Create a virtualenv by running `python3 -m venv venv`
* Activate the virtualenv by running `source venv/bin/activate`
* Install the dependencies by running `pip install -r requirements.txt`
* Install pre-commit hooks by running `pre-commit install`
* Make sure migrations are included if any model has been changed. Pre-commit hook will let you know if any migrations are missing

### Running the server locally
* Make sure you have docker installed
* Start the docker container by running `docker-compose up`
* Rename `env.example` to `.env` current one should be fine but update the values if needed, 
* Run the server by running `python manage.py runserver`
* For performance testing you can use `performancetest/gunicorn-run.sh`

## Development Guidelines
* For python let's follow the patterns https://docs.quantifiedcode.com/python-anti-patterns/index
* For the code design and practice, let's follow the [domain design pattern](https://martinfowler.com/tags/domain%20driven%20design.html) as much as applicable
* For structuring the code and separating the business logic and db logic, Let's try to do the following:
  * `models.py` - Should contain the database models
  * `services/` - Should contain the business logic
  * `repositories/` - Should contain the database interfaces (e.g., get_user_by_id, get_user_by_email)
  * `serializers/schemas/` - Should contain the serializers for the models/domain-specific data. For new APIs, use django-ninja
  * `api/` - Should contain the API endpoints. Use django-ninja for building new APIs

## Testing Guidelines

This project follows strict testing practices:

- **Unit tests**: Test logic of a single function/class; mock external dependencies
- **Integration tests**: Test components together with real DB/Redis/MQTT; minimal mocks
- **E2E tests**: Full system running; as close to real as possible

**What to mock:**
✅ External APIs, Email sending, Celery `.delay()` calls (in unit tests), Time/randomness

**What NOT to mock:**
❌ Business logic, Django ORM/models, Message schemas, Celery task bodies, Django views/serializers

See [Test Preferences in .claude_context.md](.claude_context.md) for complete testing matrix.

## Code Quality

```bash
# Format code
ruff format

# Lint check
ruff check

# Run tests
pytest

# Run with coverage
./coverage.sh
```

**Code Style:**
- Follow [Python Anti-Patterns](https://docs.quantifiedcode.com/python-anti-patterns/index)
- Use double quotes for strings
- Line length: 88 characters max
- Target Python 3.10 compatibility

---

## [Helpful Commands for Troubleshooting (Click Here)](Troubleshooting.md)


## 🤖 Working with Claude AI

This project includes an intelligent context management system for efficient AI-assisted development. See [.claude/README.md](.claude/README.md) for complete details.

### Quick Start with Claude

```bash
# Generate fresh context before starting work
make claude-context
```

Then in your Claude chat:
```
"Read .claude_context.md and .claude_context_auto.md"
```

**What this gives you:**
- ✅ Claude instantly understands the entire project architecture
- ✅ Automatically follows your strict testing guidelines
- ✅ 32 predefined code flows for efficient navigation
- ✅ Auto-generated context from latest git state

**Common commands:**
```bash
make claude-context              # Generate fresh context
make list-flows                  # See all 32 available flows
make claude-flow FLOW=<n>     # Read files for a specific flow
```

**Example flows:**
- `authorization_flow` - Token authorization MQTT → OCPI
- `session_management_flow` - Session lifecycle
- `payment_system` - Stripe payment processing
- `settlement_reporting` - CDR billing reports

See [Claude Quick Start](.claude/docs/CLAUDE_QUICK_START.md) for detailed usage patterns.

---

_Note: This is a work in progress and will be updated as we go along_
