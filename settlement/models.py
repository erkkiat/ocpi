from typing import Optional

from django.db import models
from django.db.models import Sum

from settlement.dataclasses import InvoiceData


class Invoice(models.Model):
    # Who is billing
    cpo = models.ForeignKey(
        "ocpi22.CredentialsRole",
        on_delete=models.PROTECT,
        related_name="cpo_invoices",
        null=True,
    )
    # Who is to be billed
    msp = models.ForeignKey(
        "ocpi22.CredentialsRole",
        on_delete=models.PROTECT,
        related_name="msp_invoices",
        null=True,
    )

    class BillingChoices(models.TextChoices):
        NOT_BILLED = "NO", "Not billed yet"
        INVOICED = "IN", "Invoice has been created"
        SENT = "SE", "Invoice has been sent to MSP"
        PAID = "PA", "MSP has paid invoice in full"
        CLOSED = "CL", "Closed (CPO has been paid)"

    # Todo: Logging, when did each step happen and have there been any errors

    billing_status = models.CharField(
        max_length=2, choices=BillingChoices.choices, default="NO"
    )

    # The identifier of this invoice in SAP or other finance system
    number = models.CharField(max_length=36, null=True, blank=True)

    settled_with = models.ForeignKey(
        "settlement.Invoice",
        on_delete=models.PROTECT,
        related_name="settlements",
        null=True,
        blank=True,
    )

    def totals(self) -> Optional[InvoiceData]:
        transactions = self.cdrs
        if transactions.count():
            result = InvoiceData(
                currency=transactions[0].currency,
                total_cost_excl_vat=transactions.aggregate(Sum("total_cost_excl_vat")),
                total_cost_incl_vat=transactions.aggregate(Sum("total_cost_incl_vat")),
                total_energy=transactions.aggregate(Sum("total_energy")),
                total_time=transactions.aggregate(Sum("total_time")),
                transactions=transactions.count(),
            )
            return result
        return None
