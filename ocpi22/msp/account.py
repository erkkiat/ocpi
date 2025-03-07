from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class Account(models.Model):
    customer = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="accounts"
    )
    app_token_id = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True, blank=True
    )
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)


class Transaction(models.Model):
    class Meta:
        ordering = ["datetime"]

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="transactions"
    )
    cdr = models.ForeignKey(
        "ocpi22.Cdr", blank=True, null=True, on_delete=models.DO_NOTHING
    )

    delta = models.DecimalField(max_digits=6, decimal_places=2)
    balance_after = models.DecimalField(max_digits=6, decimal_places=2)
    discount = models.IntegerField(default=0)

    pos_reference = models.CharField(max_length=36, blank=True, null=True)

    datetime = models.DateTimeField()
