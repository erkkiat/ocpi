from django.db import models


class OCPIEnergySourceCategory(models.TextChoices):
    NUCLEAR = "NUCLEAR"
    GENERAL_FOSSIL = "GENERAL_FOSSIL"
    COAL = "COAL"
    GAS = "GAS"
    GENERAL_GREEN = "GENERAL_GREEN"
    SOLAR = "SOLAR"
    WIND = "WIND"
    WATER = "WATER"


class OCPIEnvironmentalImpactCategory(models.TextChoices):
    NUCLEAR_WASTE = "NUCLEAR_WASTE"
    CARBON_DIOXIDE = "CARBON_DIOXIDE"


class OCPIEnvironmentalImpact(models.Model):
    source = models.CharField(
        max_length=14,
        choices=OCPIEnvironmentalImpactCategory.choices,
    )
    amount = models.DecimalField(max_digits=5, decimal_places=2)


class OCPIEnergySource(models.Model):
    source = models.CharField(
        max_length=20,
        choices=OCPIEnergySourceCategory.choices,
    )
    percentage = models.DecimalField(max_digits=5, decimal_places=2)


class OCPIEnergyMix(models.Model):
    is_green_energy = models.BooleanField()
    energy_sources = models.ManyToManyField(OCPIEnergySource, blank=True)
    environ_impact = models.ManyToManyField(OCPIEnvironmentalImpact, blank=True)
    supplier_name = models.CharField(max_length=255, blank=True, null=True)
    energy_product_name = models.CharField(max_length=255)
