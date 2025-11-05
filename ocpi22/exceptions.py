from django.core.exceptions import ValidationError


class EvseOccupiedError(ValidationError):
    pass


class EvseNotFoundError(ValidationError):
    pass


class LocationNotFoundError(ValidationError):
    pass


class ConnectorNotFoundError(ValidationError):
    pass
