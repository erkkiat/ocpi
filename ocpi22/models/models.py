from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from ocpi22.util import ModelUtilMixin


class AuthorizationInfo(models.Model, ModelUtilMixin):

    # Status of the Token, and whether charging is allowed at the optionally given location.
    ALLOWED_CHOICES = (
        ('ALLOWED', 'Allowed'),
        ('BLOCKED', 'Blocked'),
        ('EXPIRED', 'Expired token'),
        ('NO_CREDIT', 'User has ho credit'),
        ('NOT_ALLOWED', 'Not allowed'),
    )
    allowed = models.CharField(max_length=11, choices=ALLOWED_CHOICES)

    # The complete Token object for which this authorization was requested.
    token = models.ForeignKey('Token', on_delete=models.PROTECT)

    # Optional reference to the location if it was included in the request, and if the EV driver is allowed
    # to charge at that location. Only the EVSEs the EV driver is allowed to charge at are returned.
    # location = models.ForeignKey(Location, on_delete=models.PROTECT)

    # Reference to the authorization given by the eMSP, when given, this reference will be provided
    # in the relevant Session and/or CDR.
    authorization_reference = models.CharField(max_length=36, blank=True, default='')

    last_updated = models.DateTimeField(auto_now=True)

# Todo: OCPI tariff_id has to contain a valid OCHP tariffId (NLEVNT12345ABC)


class Facility(models.Model, ModelUtilMixin):
    class Meta:
        verbose_name_plural = 'facilities'
    name = models.CharField(max_length=15)
    description = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return self.name


class Capability(models.Model, ModelUtilMixin):
    class Meta:
        verbose_name_plural = 'capabilities'
    name = models.CharField(max_length=32)
    description = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return self.name


# Todo: CDR.id must contain the CPO-ID (NLEVN12345ABCDEFG...) [up to 36 characters total]
# Todo: CDR.id must follow the pattern: Regular Expression: [0-9A-Z]{1,36}


@receiver(post_save)
def atomic_post_save(sender, instance, **kwargs):
    """
    This makes sure that updates are sent only once per atomic operation. There was a problem
    with post_save being triggered first when a new Location is saved, then again with Evses and Connectors.
    """
    if hasattr(instance, "atomic_post_save") and transaction.get_connection().in_atomic_block:
        transaction.on_commit(lambda: instance.atomic_post_save(**kwargs))


# Todo: Prevent creating EVSE linked to a Location owned by another party
