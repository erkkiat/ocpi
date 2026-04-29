from django.db import models

from ocpi22 import choices


class DisplayText(models.Model):
    language = models.CharField(
        max_length=2,
        choices=choices.LANGUAGE_CHOICES.sort(key=lambda x: x[1]),
        verbose_name="Language",
    )
    text = models.CharField(max_length=512, verbose_name="Text")

    def __str__(self):
        return f"[{self.language}] {self.text}"
