from django.db import models

from webhooks.choices import WebhookEventChoices

from django.utils.translation import gettext as _

from ocpi22.util import build_absolute_uri


class Webhook(models.Model):
    event = models.CharField(max_length=10, unique=True, choices=WebhookEventChoices.choices, verbose_name=_('Event'))
    url = models.URLField(verbose_name=_('URL'))

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created at'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated at'))

    def __str__(self):
        return self.get_event_display()

    def get_admin_url(self):
        from util import reverse
        return build_absolute_uri(reverse('webhook-detail', args=[self.event]))
