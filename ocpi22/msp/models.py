from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

PHONE_FIELD_LENGTH = 20
VEHICLE_FIELD_LENGTH = 40


class Profile(models.Model):
    user = models.OneToOneField(User, related_name='profile', on_delete=models.CASCADE, primary_key=True)
    phone = models.CharField(max_length=PHONE_FIELD_LENGTH, blank=True)
    vehicle = models.CharField(max_length=VEHICLE_FIELD_LENGTH, blank=True)


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **_kwargs):
    if created:
        Profile.objects.create(user=instance)
