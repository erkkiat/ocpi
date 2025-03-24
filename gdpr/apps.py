from django.apps import AppConfig


class GdprConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gdpr"

    def ready(self):
        from gdpr.model import LocationNERModel

        LocationNERModel.get_instance()
