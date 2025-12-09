from django.conf import settings
from ninja import Router

from custom_ninja_api import CustomNinjaAPI
from ocpi22.ocpi.auth import NinjaBasicAuth, HubjectCertAuth


def get_hubject_auth():
    return HubjectCertAuth() if settings.ENABLE_HUBJECT else NinjaBasicAuth()


api = CustomNinjaAPI(
    auth=NinjaBasicAuth(),
    urls_namespace="hubject-api",
)

remote_command_router = Router()

api.add_router(
    "api/oicp/charging/v21/",
    remote_command_router,
    tags=["Hubject Remote Commands"],
    auth=get_hubject_auth(),
)
