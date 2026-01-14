# Type Checking Guide for OCPI Connector

## Overview

This project now requires **strict type hints for all new code**. This document explains how to use the type checking infrastructure.

## Quick Start

### Check your code

```bash
# Check a single file
mypy --config-file=mypy.ini --ignore-missing-imports path/to/file.py

# Check a directory
mypy --config-file=mypy.ini --ignore-missing-imports ocpi22/locations/

# Check specific files
mypy --config-file=mypy.ini --ignore-missing-imports file1.py file2.py
```

### Pre-commit Hook

Type checking runs automatically when you commit:

```bash
# Install pre-commit hooks (one time)
pre-commit install

# Test hooks manually
pre-commit run mypy --all-files
```

### CI Integration

- Type checking runs automatically on all PRs via GitHub Actions
- Workflow: `.github/workflows/type-check.yml`
- Currently informational only (won't fail builds)

## Type Hints Requirements

### All New Code Must Have:

1. **Function/Method Signatures**
   ```python
   def get_session_by_uid(session_uid: str) -> Optional[Session]:
       pass
   ```

2. **Class Attributes**
   ```python
   class LocationService:
       repository: LocationRepository
   ```

3. **Instance Variables**
   ```python
   def __init__(self, repo: LocationRepository) -> None:
       self.repo: LocationRepository = repo
   ```

### Common Patterns

#### Services

```python
from typing import Optional, List
from ocpi22.models import Session

class SessionService:
    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository
    
    def get_active_sessions(self, country: str) -> List[Session]:
        return self.repository.filter_active(country)
    
    def find_by_id(self, session_id: int) -> Optional[Session]:
        try:
            return self.repository.get_by_id(session_id)
        except Session.DoesNotExist:
            return None
```

#### Repositories

```python
from typing import Optional, List
from django.db.models import QuerySet
from ocpi22.models import Location

class LocationRepository:
    def get_by_uid(self, uid: str) -> Optional[Location]:
        return Location.objects.filter(uid=uid).first()
    
    def list_active(self) -> QuerySet[Location]:
        return Location.objects.filter(publish=True)
    
    def create(self, **kwargs) -> Location:
        return Location.objects.create(**kwargs)
```

#### API Views (Django Ninja)

```python
from django.http import HttpRequest, JsonResponse
from ocpi22.models import Session

def get_session_endpoint(request: HttpRequest, session_id: str) -> JsonResponse:
    service = SessionService(repository=SessionRepository())
    session = service.find_by_id(session_id)
    
    if not session:
        return JsonResponse({"error": "Not found"}, status=404)
    
    return JsonResponse({"session": serialize_session(session)})
```

## Type Checking Configuration

### mypy.ini

The configuration file is located at the project root. Key settings:

- **Python Version**: 3.11
- **Strict Mode**: Disabled for gradual adoption
- **Ignore Missing Imports**: Enabled for third-party libraries
- **Django Plugins**: Commented out (requires full environment)

### Ignoring Specific Errors

When necessary, you can ignore specific type errors:

```python
# mypy: ignore-errors
# Use sparingly and only when absolutely necessary

def legacy_function(data):  # type: ignore[no-untyped-def]
    # Legacy code without types
    pass
```

## Common Type Hints

### Built-in Types

```python
from typing import Optional, List, Dict, Tuple, Set, Union, Any

# Optional (can be None)
def get_user(user_id: int) -> Optional[User]:
    pass

# Lists
def get_users() -> List[User]:
    pass

# Dictionaries
def get_metadata() -> Dict[str, Any]:
    pass

# Multiple possible types
def process(data: Union[str, int]) -> str:
    pass
```

### Django-Specific Types

```python
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse

# QuerySets
def get_active_locations() -> QuerySet[Location]:
    return Location.objects.filter(publish=True)

# HTTP Types
def my_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
```

### Pydantic Models

```python
from pydantic import BaseModel

class LocationSchema(BaseModel):
    uid: str
    name: str
    address: str
    
def validate_location(data: dict) -> LocationSchema:
    return LocationSchema(**data)
```

## Best Practices

1. **Always annotate new functions**
   - Parameters and return types are mandatory
   
2. **Use Optional for nullable values**
   ```python
   def find_user(user_id: int) -> Optional[User]:  # Can return None
       pass
   ```

3. **Annotate class attributes**
   ```python
   class Service:
       repository: Repository  # Clear attribute type
   ```

4. **Use Any sparingly**
   - Only when type is truly unknown
   - Consider Union[...] for known alternatives

5. **Don't annotate obvious literals**
   ```python
   # No need to annotate
   count = 0
   name = "default"
   
   # But do annotate when not obvious
   result: List[str] = []
   ```

## Troubleshooting

### "Module not found" errors

Add to `mypy.ini`:
```ini
[mypy-module_name]
ignore_missing_imports = True
```

### Django initialization errors

Use `--ignore-missing-imports` flag or disable Django plugins in mypy.ini

### Circular import errors

Use string annotations:
```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import User

def process_user(user: "User") -> None:
    pass
```

## Examples

See `typing_examples.py` in the project root for comprehensive examples of:
- Service classes with typed methods
- Repository patterns
- API view handlers
- Utility functions
- Working with Optional types

## Resources

- [MyPy Documentation](https://mypy.readthedocs.io/)
- [Python Type Hints Cheat Sheet](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html)
- [Django-Stubs Documentation](https://github.com/typeddjango/django-stubs)
- [Type Hints in Real Python](https://realpython.com/python-type-checking/)

## Questions?

- Review `typing_examples.py` for patterns
- Check existing typed code in the project
- Consult CLAUDE.md for project-specific guidelines
