import logging
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone

from ocpi22.models.session import Session
from ocpi22.models.token import Token
from ocpi22.ocpi.util import generate_token_id


class Account(models.Model):
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='accounts')
    app_token_id = models.CharField(max_length=settings.OCPI_22_MAX_UID_LENGTH, db_index=True, blank=True)
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY)

    @property
    def balance(self) -> Decimal:
        last_transaction: Transaction = self.transactions.last()
        if last_transaction:
            return last_transaction.balance_after
        return Decimal(0.0)

    def __str__(self):
        return f'{self.customer.username} account {self.pk} balance {self.balance}'

    def deposit(self, amount: Decimal, **kwargs) -> Decimal:
        transaction = Transaction.objects.create(
            account=self, delta=amount, balance_after=self.balance + amount, datetime=timezone.now(), **kwargs
        )
        return transaction.balance_after

    def withdraw(self, amount: Decimal, cdr: "Cdr", pos_reference: str, **kwargs) -> balance:
        balance = self.deposit(-abs(amount), pos_reference=pos_reference, cdr=cdr, **kwargs)
        if balance <= 0:
            logging.error(f'{self} has negative balance')


class Transaction(models.Model):
    class Meta:
        ordering = ['datetime']

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='transactions')
    cdr = models.ForeignKey("ocpi22.Cdr", blank=True, null=True, on_delete=models.DO_NOTHING)

    # Todo: add field for VAT?

    delta = models.DecimalField(max_digits=6, decimal_places=2)
    balance_after = models.DecimalField(max_digits=6, decimal_places=2)
    discount = models.IntegerField(default=0)

    pos_reference = models.CharField(max_length=36, blank=True, null=True)

    datetime = models.DateTimeField()

    def __str__(self):
        return f'Transaction {self.delta}{self.account.currency}, balance after: {self.balance_after}{self.account.currency}'

    @property
    def description(self) -> str:
        if self.delta > 0:
            return 'Payment / deposit'
        cdr = self.cdr
        if not cdr:
            return 'No details available'
        return f'Charged {cdr.total_energy} kWh at ' \
               f'"{cdr.cdr_location_name}", {cdr.cdr_location_city}'


def get_user_account(session: Session) -> Optional[Account]:
    if not session:
        return None
    token = Token.get_if_exists(uid=session.cdr_token_uid)
    if token:
        if token.customer:
            return token.customer.accounts.first()
    return Account.objects.filter(app_token_id=session.cdr_token_uid).first()


def check_balance(session: Session):
    """
    Check balance and stop charging if money is about to run out
    """
    cost = session.total_cost_incl_vat
    account = get_user_account(session)
    if (account and cost):
        remaining = account.balance - Decimal(cost)
        # print(f'Balance: {account.balance}, cost: {cost}, remaining: {remaining}')
        if remaining < 0.5:
            logging.error(f'Account #{account.pk} balance used, stopping session #{session.uid}')
            from ocpi22.commands.commands import send_stop_command
            if not send_stop_command(session):
                logging.error(f'Unable to stop session #{session.uid} with account balance reaching zero')


def update_balance(cdr) -> None:
    account = get_user_account(cdr.session)
    if account:
        # Todo: do the payment callback
        account.withdraw(Decimal(-cdr.total_cost_incl_vat), cdr=cdr, pos_reference='N/A')
    else:
        logging.error(f'{settings.HOSTNAME}: Unable to create user transaction for CDR #{cdr.uid} - {cdr}: '
                      f'customer has no account to be found')


@receiver(pre_save, sender=Account)
def account_pre_save(sender, instance: Account, **_kwargs):
    if not instance.app_token_id:
        instance.app_token_id = generate_token_id()
