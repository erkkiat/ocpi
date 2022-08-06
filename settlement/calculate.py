from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import QuerySet, Sum
from icecream import ic

from ocpi22.models.credentials import Credentials


@dataclass(eq=True, frozen=True)
class InvoiceData:
    currency: str
    total_cost_excl_vat: Decimal
    total_cost_incl_vat: Decimal
    total_energy: Decimal
    total_time: Decimal
    transactions: int


def calculate_invoice_data(credentials: Credentials, end_date: date, start_date: date = None) -> Optional[InvoiceData]:
    transactions: QuerySet = credentials.cdrs.filter(
        start_date_time__gte=start_date or date(2000, 1, 1),
        end_date_time__lt=end_date
    )
    if transactions.count():
        result = InvoiceData(
            currency=transactions[0].currency,
            total_cost_excl_vat=transactions.aggregate(Sum('total_cost_excl_vat')),
            total_cost_incl_vat=transactions.aggregate(Sum('total_cost_incl_vat')),
            total_energy=transactions.aggregate(Sum('total_energy')),
            total_time=transactions.aggregate(Sum('total_time')),
            transactions=transactions.count(),
        )
        return result


def create_invoice(credentials: Credentials, end_date=None, start_date: date = None):
    invoice = calculate_invoice_data(credentials, end_date or date.today(), start_date)
    # ic(invoice)
    return invoice
