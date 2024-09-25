from enum import Enum

from django.contrib.auth.models import User
from django.db import models

from ocpi22.util import CURRENCY_CHOICES


#
# Stripe
#

# Customer OneToOne Django User (Ei näy läpi Payment-luokasta, vaan kytkeytyy suoraan Useriin?)
# PaymentMethod ForeignKey to Customer
# Payment ForeignKey to Customer/PaymentMethod?
#  - PaymentIntent
#  - Status
#  - How much captured


class Customer(models.Model):
    user = models.OneToOneField(
        User, related_name="payment_customer", on_delete=models.PROTECT
    )
    customer_id = models.CharField(max_length=64)

    def __str__(self):
        return self.user.email


class PaymentMethod(models.Model):
    payment_method_id = models.CharField(max_length=64)
    customer = models.ForeignKey(
        Customer, related_name="payment_methods", on_delete=models.PROTECT
    )

    def __str__(self):
        return str(self.payment_method_id)


class PaymentStatusEnum(Enum):
    RESERVED = "RV"
    COMPLETED = "CM"
    REFUNDED = "RE"
    PARTIALLY_REFUNDED = "PR"
    ERROR = "ER"


PAYMENT_CHOICES = [
    (x.value, x.name.capitalize().replace("_", " ")) for x in PaymentStatusEnum
]


class Payment(models.Model):
    session_id = models.CharField(max_length=64, db_index=True)
    payment_method = models.ForeignKey(
        PaymentMethod, related_name="payments", on_delete=models.PROTECT
    )
    status = models.CharField(choices=PAYMENT_CHOICES, max_length=2)
    amount = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    currency = models.CharField(choices=CURRENCY_CHOICES, max_length=3)
    provider_data = models.JSONField(null=True, blank=True)

    # Django automatic dates
    updated = models.DateTimeField(auto_now=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.payment_method.customer.user.email} {self.get_status_display()} {self.amount} {self.currency}"

    @property
    def user(self) -> User:
        return self.payment_method.customer.user

    @property
    def email(self) -> str:
        return self.user.email
