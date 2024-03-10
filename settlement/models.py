from django.db import models


class Invoice(models.Model):
    # Who is to be billed
    msp = models.ForeignKey("ocpi22.CredentialsRole", on_delete=models.PROTECT, related_name='invoices', null=True)

    class BillingChoices(models.TextChoices):
        NOT_BILLED = 'NO', 'Not billed yet'
        INVOICED = 'IN', 'Invoice has been created'
        SENT = 'SE', 'Invoice has been sent to MSP'
        PAID = 'PA', 'MSP has paid invoice in full'
        CLOSED = 'CL', 'Closed (CPO has been paid)'

    # Todo: Logging, when did each step happen and have there been any errors

    billing_status = models.CharField(max_length=2, choices=BillingChoices.choices, default='NO')

    number = models.CharField(max_length=36, null=True, blank=True)

    payment_system_foreignkey = models.CharField(max_length=128, null=True, blank=True)

    # Which payments processor has been used for getting the payment from MSP and sending payment to CPO
    class PaymentProcessorChoices(models.TextChoices):
        STRIPE = 'ST', 'Stripe'
        PAYPAL = 'PP', 'Paypal'
        OPENCART = 'OC', 'OpenCart'
        CUSTOM = 'CU', 'Custom'

    payment_system = models.CharField(max_length=2, choices=PaymentProcessorChoices.choices, null=True, blank=True)

    # @cached_property
    # def totals(self) -> Optional[InvoiceData]:
    #     transactions = self.cdrs
    #     if transactions.count():
    #         result = Invoice(
    #             currency=transactions[0].currency,
    #             total_cost_excl_vat=transactions.aggregate(Sum('total_cost_excl_vat')),
    #             total_cost_incl_vat=transactions.aggregate(Sum('total_cost_incl_vat')),
    #             total_energy=transactions.aggregate(Sum('total_energy')),
    #             total_time=transactions.aggregate(Sum('total_time')),
    #             transactions=transactions.count(),
    #         )
    #         return result

    # Seuraavaksi: luo oikea Invoice laskuttamattomista CDRstä kyseiselle billed_to (tai siis kaikille)
    # InvoiceAdmin
