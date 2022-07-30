from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import QuerySet, Sum
from icecream import ic

from ocpi22.models.cdr import Cdr
from ocpiconnector.ocpi_identities import Party


@dataclass(eq=True, frozen=True)
class Invoice:
    currency: str
    total_cost_excl_vat: Decimal
    total_cost_incl_vat: Decimal
    total_energy: Decimal
    total_time: Decimal
    transactions: int


def calculate_invoice_data(billed_to: str, start_date: date, end_date: date) -> Optional[Invoice]:
    transactions: QuerySet = Cdr.objects.filter(
        billed_to=billed_to,
        start_date_time__gte=start_date,
        end_date_time__lt=end_date
    )
    if transactions.count():
        result = Invoice(
            currency=transactions[0].currency,
            total_cost_excl_vat=transactions.aggregate(Sum('total_cost_excl_vat')),
            total_cost_incl_vat=transactions.aggregate(Sum('total_cost_incl_vat')),
            total_energy=transactions.aggregate(Sum('total_energy')),
            total_time=transactions.aggregate(Sum('total_time')),
            transactions=transactions.count(),
        )
        return result
