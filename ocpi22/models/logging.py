from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class LogTopic(models.TextChoices):
    FULL_PULL = 'FP', _('Full update')
    GENERIC = 'GN', _('Generic errors')


class LogEntry(models.Model):
    class Meta:
        verbose_name_plural = _('log entries')

    topic = models.CharField(max_length=2, choices=LogTopic.choices, verbose_name=_('topic'))

    # Django automatic dates
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created on'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('updated on'))

    def __str__(self):
        date = self.updated.strftime(settings.DATE_FORMAT)
        return f'{self.get_topic_display()} {date}'


class LogLevel(models.TextChoices):
    DEBUG = 'D', _('Debug')
    INFO = 'I', _('Information')
    WARNING = 'W', _('Warning')
    ERROR = 'E', _('Error')
    CRITICAL = 'C', _('Critical')


class ChildEvent(models.Model):
    logentry = models.ForeignKey(LogEntry, on_delete=models.CASCADE, related_name='events')

    level = models.CharField(max_length=1, choices=LogLevel.choices, verbose_name=_('level'))
    text = models.TextField()

    message = models.JSONField(null=True, blank=True, verbose_name=_('message'))
    response = models.JSONField(null=True, blank=True, verbose_name=_('response'))

    # Django automatic dates
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created on'))

    def __str__(self):
        return self.text
