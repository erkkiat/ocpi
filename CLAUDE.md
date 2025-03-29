# CLAUDE.md - Guide for Agentic Coding in OCPI Connector

## Build & Test Commands
- Run server: `python manage.py runserver`
- Run tests: `pytest` (all tests)
- Run single test: `pytest path/to/test_file.py::TestClass::test_function -v`
- Run with coverage: `./coverage.sh` or `coverage run --source='.' manage.py test`
- Code formatting: `ruff format`
- Lint check: `ruff check`

## Code Style Guidelines
- Follow [Python Anti-Patterns](https://docs.quantifiedcode.com/python-anti-patterns/index)
- Use double quotes for strings (like Black)
- Line length: 88 characters max
- Indent with 4 spaces
- Target Python 3.10 compatibility

## Project Structure
- `models.py` - Database models only
- `services/` - Business logic
- `repositories/` - Database interfaces
- `serializers/schemas/` - Data serialization
- `api/` - API endpoints (use django-ninja for new APIs)

## Pre-commit Workflow
- Install hooks: `pre-commit install`
- Ensure migrations are included for model changes