from ninja_extra import NinjaExtraAPI
from ninja_jwt.controller import NinjaJWTDefaultController

api = NinjaExtraAPI(urls_namespace='jwt')
api.register_controllers(NinjaJWTDefaultController)
