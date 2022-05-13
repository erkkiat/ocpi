import logging
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from ocpi22.models.session import Session


class Account(models.Model):
    # Todo: What language does the customer use? Show feedback in that language
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
    cdr = models.ForeignKey("Cdr", blank=True, null=True, on_delete=models.DO_NOTHING)

    delta = models.DecimalField(max_digits=6, decimal_places=2)
    balance_after = models.DecimalField(max_digits=6, decimal_places=2)
    discount = models.IntegerField(default=0)

    pos_reference = models.CharField(max_length=36, blank=True, null=True)

    datetime = models.DateTimeField()

    def __str__(self):
        return f'Transaction {self.delta}{self.account.currency}, balance after: {self.balance_after}{self.account.currency}'


def get_user_account(session: Session) -> Optional[Account]:
    if not session:
        return None
    return Account.objects.filter(app_token_id=session.cdr_token_uid).first()


def check_balance(session: Session):
    """
    Check balance and stop charging if money is about to run out
    """
    cost = session.total_cost_incl_vat
    account = get_user_account(session)
    if (account and cost):
        remaining = account.balance - Decimal(cost)
        print(f'Balance: {account.balance}, cost: {cost}, remaining: {remaining}')
        if remaining < 0.5:
            print('Balance used, stopping charging')
            from ocpi22.commands.commands import send_stop_command
            if not send_stop_command(session):
                logging.error(f'Unable to stop session {session} with account balance is reaching zero')


def update_balance(cdr) -> None:
    account = get_user_account(cdr.session)
    if account:
        Transaction.objects.create(account=account, cdr=cdr, delta=-cdr.total_cost_incl_vat,
                                   balance_after=account.balance - Decimal(cdr.total_cost_incl_vat),
                                   datetime=timezone.now())
    else:
        logging.error(f'Unable to create user transaction for CDR {cdr}')
