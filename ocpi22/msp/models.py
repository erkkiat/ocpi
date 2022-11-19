import gdpr_assist
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from gdpr_assist.signals import pre_anonymise

PHONE_FIELD_LENGTH = 20
VEHICLE_FIELD_LENGTH = 40


class UserPrivacyMeta:
    fields = ['first_name', 'last_name', 'email', 'username']


gdpr_assist.register(User, UserPrivacyMeta, gdpr_default_manager_name="objects_anonymised")


class Profile(models.Model):
    user = models.OneToOneField(User, related_name='profile', on_delete=models.CASCADE, primary_key=True)
    phone = models.CharField(max_length=PHONE_FIELD_LENGTH, blank=True)
    vehicle = models.CharField(max_length=VEHICLE_FIELD_LENGTH, blank=True)

    class PrivacyMeta:
        fields = ['vehicle', 'phone']

        def search(self, value):
            return self.model.objects.filter(Q(user__email__icontains=value) | Q(user__first_name__icontains=value) | Q(
                user__last_name__icontains=value))

        def export(self, instance):
            return {
                'email': instance.user.email,
                'first_name': instance.user.first_name,
                'last_name': instance.user.last_name,
                'phone': instance.phone,
                'vehicle': instance.vehicle,
                'password': '********'
            }

    def __str__(self):
        return f'{self.user} {self.phone}'


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **_kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(pre_anonymise, sender=Profile)
def anonymise_related(sender, instance, **kwargs):
    instance.user.anonymise()
