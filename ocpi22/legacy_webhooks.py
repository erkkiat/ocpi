from logging import getLogger
from typing import Optional, Union

from django.conf import settings

from ocpi22.models.location import Location, Evse

logger = getLogger(__name__)


def send_to_webhook(
    data: Union[dict, Location, Evse] = None,
    serializer=None,
    serialized_data=None,
    outbound_serializer=None,
    timeout=10,
    ocpi_master=None,
) -> Optional[dict]:
    """
    Webhook function - temporarily disabled.
    Only remote command webhooks are handled by the new webhook system.
    """
    if settings.PERFORMANCE_TEST:
        return {}

    serializer_name = serializer.__class__.__name__ if serializer else "Unknown"
    logger.info(f"Webhook disabled for serializer: {serializer_name}")
    return {}
