from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ocpi22.models.credentials import CredentialsRole, Credentials


@dataclass
class InvoiceTotals:
    cpo: "CredentialsRole"
    msp: "CredentialsRole"
    total: float
    currency: str


@dataclass
class SettlementData:
    start_datetime: datetime
    end_datetime: datetime
    amount: float
    currency: str
    who_bills: "Credentials"
    who_pays: "Credentials"
    totals: list[InvoiceTotals] = field(default_factory=list)


@dataclass(eq=True, frozen=True)
class InvoiceData:
    currency: str
    total_cost_excl_vat: Decimal
    total_cost_incl_vat: Decimal
    total_energy: Decimal
    total_time: Decimal
    transactions: int
