from django.db import models
from django.utils.html import format_html

from ocpi22.util import ModelUtilMixin


class BusinessDetails(models.Model, ModelUtilMixin):
    class Meta:
        verbose_name = "roaming party"
        verbose_name_plural = "roaming parties"
        indexes = [
            models.Index(fields=["name", "website"]),
        ]

    name = models.CharField(max_length=100)
    website = models.URLField(blank=True, null=True)
    logo = models.ForeignKey(
        "OCPIImage", blank=True, null=True, on_delete=models.CASCADE
    )

    def __str__(self):
        return self.name

    def referenced_locations(self):
        return (
            self.owner_locations.all().count()
            + self.operator_locations.all().count()
            + self.owner_locations.all().count()
        )

    def referenced_credentials(self):
        return self.credentialsroles.all().count()

    def admin_party_ids(self):
        roles = self.credentialsroles.all()
        return format_html("<br>".join([str(role) for role in roles]))

    admin_party_ids.short_description = "Party IDs"
    admin_party_ids.allow_tags = True
    admin_party_ids.admin_order_field = "credentialsroles"
