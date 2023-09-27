# from django.db import models
#
# from ocpi22.choices import CERTIFICATION_TOPIC_CHOICES
#
#
# class CertificationStep(models.Model):
#     """A step in the certification process"""
#
#     topic = models.CharField(max_length=13, choices=CERTIFICATION_TOPIC_CHOICES)
#     action = models.CharField(max_length=256)
#
#     passed = models.BooleanField(default=False)
#     created = models.DateTimeField(auto_now_add=True)
#
#     errors = models.TextField(null=True, blank=True)
#
#     credentials = models.ForeignKey('ocpi22.Credentials', on_delete=models.CASCADE, null=True, blank=True,
#                                     related_name='certification_step_list')
