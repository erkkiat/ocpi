from django.db import models


class OCPIImageCategory(models.TextChoices):
    CHARGER = "CHARGER"
    ENTRANCE = "ENTRANCE"
    LOCATION = "LOCATION"
    NETWORK = "NETWORK"
    OPERATOR = "OPERATOR"
    OTHER = "OTHER"
    OWNER = "OWNER"


class OCPIImage(models.Model):
    url = models.URLField()
    thumbnail = models.URLField(blank=True, null=True)
    category = models.CharField(
        max_length=8,
        choices=OCPIImageCategory.choices,
    )
    image_type = models.CharField(max_length=4)
    width = models.PositiveIntegerField(blank=True, null=True)
    height = models.PositiveIntegerField(blank=True, null=True)
