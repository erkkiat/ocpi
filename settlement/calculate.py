from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pytz
from django.db.models import QuerySet, Sum
from django.utils.datetime_safe import datetime
from icecream import ic

from ocpi22.models.credentials import Credentials
from ocpiconnector import settings


@dataclass(eq=True, frozen=True)
class InvoiceData:
    currency: str
    total_cost_excl_vat: Decimal
    total_cost_incl_vat: Decimal
    total_energy: Decimal
    transactions: int


def calculate_invoice_data(credentials: Credentials, end_date: datetime, start_date: datetime = None) -> Optional[InvoiceData]:
    transactions: QuerySet = credentials.cdrs.filter(
        start_date_time__gte=start_date or datetime(2000, 1, 1).replace(tzinfo=pytz.timezone(settings.TIME_ZONE)),
        end_date_time__lt=end_date or datetime.now().replace(tzinfo=pytz.timezone(settings.TIME_ZONE)),
    )
    if transactions.count():
        result = InvoiceData(
            currency=transactions[0].currency,
            total_cost_excl_vat=transactions.aggregate(Sum('total_cost_excl_vat')),
            total_cost_incl_vat=transactions.aggregate(Sum('total_cost_incl_vat')),
            total_energy=transactions.aggregate(Sum('total_energy')),
            transactions=transactions.count(),
        )
        return result


def create_invoice(credentials: Credentials, end_date: datetime = None, start_date: datetime = None):
    invoice = calculate_invoice_data(credentials, end_date, start_date)
    return invoice
