from django.conf import settings
from ninja import NinjaAPI, Redoc, Swagger


class CustomNinjaAPI(NinjaAPI):
    def __init__(self, *args, **kwargs):
        env = getattr(settings, "ENV", "development")

        if env == "production":
            kwargs["docs"] = None
            kwargs["docs_url"] = None
            kwargs["openapi_url"] = None
        else:
            docs_ui = getattr(settings, "NINJA_DOCS_UI", "swagger")

            if docs_ui == "redoc":
                kwargs["docs"] = Redoc()
            else:
                kwargs["docs"] = Swagger()
        super().__init__(*args, **kwargs)
