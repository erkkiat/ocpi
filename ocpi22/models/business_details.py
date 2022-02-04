from django.db import models

from ocpi22.util import ModelUtilMixin


class BusinessDetails(models.Model, ModelUtilMixin):
    class Meta:
        verbose_name_plural = 'business details'
        constraints = [
            models.UniqueConstraint(fields=['name', 'website'], name='businessdetails_name_website'),
        ]

    name = models.CharField(max_length=100)
    website = models.URLField(blank=True, default='')
    logo = models.URLField(blank=True, default='')

    def __str__(self):
        return self.name

    def referenced_locations(self):
        # noinspection PyUnresolvedReferences
        return self.owner_locations.all().count() + \
               self.operator_locations.all().count() + \
               self.owner_locations.all().count()

    def referenced_credentials(self):
        # noinspection PyUnresolvedReferences
        return self.credentialsroles.all().count()
