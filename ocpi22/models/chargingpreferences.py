from django.db import models


class OCPI221ProfileType(models.TextChoices):
    FAST = 'FAST', 'Driver wants his EV charged as quickly as possible and is willing to pay a premium for this, if needed.'
    CHEAP = 'CHEAP', 'Driver wants to use the cheapest charging profile possible.'
    GREEN = 'GREEN', 'Driver wants his EV charged with as much regenerative (green) energy as possible.'
    REGULAR = 'REGULAR', 'Driver does not have special preferences.'


class OCPI221ChargingPreferences(models.Model):
    profile_type = models.CharField(
        max_length=7,
        choices=OCPI221ProfileType.choices,
        default=OCPI221ProfileType.REGULAR,
        help_text="Type of Smart Charging Profile selected by the driver."
    )
    departure_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expected departure. The driver has given this Date/Time as expected departure moment."
    )
    energy_need = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Requested amount of energy in kWh. The EV driver wants to have this amount of energy charged."
    )
    discharge_allowed = models.BooleanField(
        default=False,
        help_text="The driver allows their EV to be discharged when needed, as long as the other preferences are met."
    )
