"""
Example service demonstrating strict typing requirements.

This file serves as a reference for all new code in the OCPI Connector project.
All new services, repositories, and utility functions must follow these typing patterns.
"""

from typing import Optional, List, Dict, Any, Union
from django.http import HttpRequest, JsonResponse
from django.db.models import QuerySet

# Example imports (these would be real in actual code)
# from ocpi22.models import Session, Location, Token
# from ocpi22.commands.repository import SessionRepository


class ExampleService:
    """
    Example service class demonstrating proper type hints.

    All service classes should:
    - Have typed __init__ methods
    - Include return type hints for all methods
    - Use Optional[] for values that might be None
    - Use List[], Dict[], etc. for collections
    """

    def __init__(self, repository: Any) -> None:  # Use actual repository type
        """
        Initialize the service with required dependencies.

        Args:
            repository: Repository instance for data access
        """
        self.repository = repository

    def get_by_id(
        self, entity_id: int
    ) -> Optional[Any]:  # Replace Any with actual model
        """
        Retrieve an entity by its ID.

        Args:
            entity_id: The unique identifier of the entity

        Returns:
            The entity if found, None otherwise
        """
        try:
            return self.repository.get_by_id(entity_id)
        except Exception:
            return None

    def create(
        self, name: str, description: str, metadata: Optional[Dict[str, Any]] = None
    ) -> Any:  # Replace Any with actual model
        """
        Create a new entity with validation.

        Args:
            name: The name of the entity
            description: A description of the entity
            metadata: Optional metadata dictionary

        Returns:
            The newly created entity

        Raises:
            ValueError: If validation fails
        """
        if not name or not description:
            raise ValueError("Name and description are required")

        return self.repository.create(
            name=name, description=description, metadata=metadata or {}
        )

    def list_active(
        self, limit: int = 100, offset: int = 0
    ) -> List[Any]:  # Replace Any with actual model
        """
        List active entities with pagination.

        Args:
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns:
            List of active entities
        """
        queryset = self.repository.get_active_queryset()
        return list(queryset[offset : offset + limit])

    def update_status(self, entity_id: int, status: str, updated_by: str) -> bool:
        """
        Update the status of an entity.

        Args:
            entity_id: The ID of the entity to update
            status: The new status value
            updated_by: Username of the user making the update

        Returns:
            True if update was successful, False otherwise
        """
        entity = self.get_by_id(entity_id)
        if not entity:
            return False

        entity.status = status
        entity.updated_by = updated_by
        entity.save()
        return True

    def process_batch(
        self, items: List[Dict[str, Any]]
    ) -> Dict[str, Union[int, List[str]]]:
        """
        Process a batch of items and return results.

        Args:
            items: List of item dictionaries to process

        Returns:
            Dictionary with success count and error messages
        """
        success_count = 0
        errors: List[str] = []

        for item in items:
            try:
                self.create(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    metadata=item.get("metadata"),
                )
                success_count += 1
            except ValueError as e:
                errors.append(str(e))

        return {"success_count": success_count, "errors": errors}


# Example repository class
class ExampleRepository:
    """Example repository demonstrating typed data access methods."""

    def get_by_id(self, entity_id: int) -> Optional[Any]:
        """Get entity by ID."""
        # Implementation would use Django ORM
        pass

    def create(self, name: str, description: str, metadata: Dict[str, Any]) -> Any:
        """Create new entity."""
        # Implementation would use Django ORM
        pass

    def get_active_queryset(self) -> QuerySet:
        """Get queryset of active entities."""
        # Implementation would use Django ORM
        # Example: return Entity.objects.filter(is_active=True)
        raise NotImplementedError("This is an example - implement in actual repository")


# Example API view with Django typing
def example_api_view(request: HttpRequest, entity_id: int) -> JsonResponse:
    """
    Example API view with proper type hints.

    Args:
        request: The HTTP request object
        entity_id: The ID of the entity to retrieve

    Returns:
        JSON response with entity data or error
    """
    service = ExampleService(repository=ExampleRepository())
    entity = service.get_by_id(entity_id)

    if not entity:
        return JsonResponse({"error": "Entity not found"}, status=404)

    return JsonResponse(
        {
            "id": entity_id,
            "name": "Example",  # Would be entity.name in real code
            "description": "Example description",
        }
    )


# Example utility function
def calculate_total_cost(
    base_price: float, quantity: int, discount_percentage: float = 0.0
) -> float:
    """
    Calculate total cost with optional discount.

    Args:
        base_price: The base price per unit
        quantity: Number of units
        discount_percentage: Discount as percentage (0-100)

    Returns:
        The total cost after discount

    Raises:
        ValueError: If inputs are invalid
    """
    if base_price < 0 or quantity < 0:
        raise ValueError("Price and quantity must be non-negative")

    if not 0 <= discount_percentage <= 100:
        raise ValueError("Discount must be between 0 and 100")

    subtotal = base_price * quantity
    discount = subtotal * (discount_percentage / 100)
    return subtotal - discount


# Example of working with Optional types
def safe_get_user_email(user_id: Optional[int]) -> Optional[str]:
    """
    Safely get user email, handling None cases.

    Args:
        user_id: User ID or None

    Returns:
        User email if found, None otherwise
    """
    if user_id is None:
        return None

    # Would query database in real implementation
    # user = User.objects.filter(id=user_id).first()
    # return user.email if user else None
    return None
