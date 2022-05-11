from django.conf import settings
from django.contrib.auth.models import User
from django.db import models

from ocpi22.models.cdr import Cdr


class Account(models.Model):
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='accounts')
    app_token_id = models.CharField(max_length=36, db_index=True)
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)

    @property
    def balance(self) -> float:
        last_transaction: Transaction = self.transactions.last()
        if last_transaction:
            return last_transaction.balance_after
        return 0.0

    def __str__(self):
        return f'{self.customer.username} account {self.pk} balance {self.balance}'


class Transaction(models.Model):
    class Meta:
        ordering = ['datetime']

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='transactions')
    cdr = models.ForeignKey(Cdr, blank=True, null=True, on_delete=models.DO_NOTHING)

    delta = models.FloatField()
    balance_after = models.FloatField()
    discount = models.FloatField(default=0.0)

    pos_reference = models.CharField(max_length=36, blank=True, null=True)

    datetime = models.DateTimeField()

    def __str__(self):
        return f'Transaction {self.delta}{self.account.currency}, balance after: {self.balance_after}{self.account.currency}'
