from ninja import Router

from custom_ninja_api import CustomNinjaAPI
from ocpi22.ocpi.auth import NinjaBasicAuth, HubjectDynamicAuth

api = CustomNinjaAPI(
    auth=NinjaBasicAuth(),
    urls_namespace="hubject-api",
)

remote_command_router = Router()

api.add_router(
    "api/oicp/charging/v21/",
    remote_command_router,
    tags=["Hubject Remote Commands"],
    auth=HubjectDynamicAuth(),
)
