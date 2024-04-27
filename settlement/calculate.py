from datetime import datetime, date
from itertools import combinations
from typing import Optional, Union

import pytz
from django.db.models import QuerySet, Sum
from django.utils.datetime_safe import datetime

from ocpi22.models.cdr import Cdr
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpiconnector import settings
from settlement.dataclasses import InvoiceTotals, SettlementData, InvoiceData
from ocpi22.credentials.util import get_entity_roles
from util import convert_to_utc_midnight, convert_to_utc_end_of_day


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


def calculate_invoice_totals(start_date: datetime, end_date: datetime) -> list[InvoiceTotals]:
    """
    Find all the CPOs who need to invoice one or more MSPs during the given time period.

    @param start_date: Inclusive start date of the period
    @param end_date: Exclusive end date of the period
    @return: A list of CredentialsRoles pairs (CPO, MSP) and the total amount to be invoiced between each pair
    """
    queryset = Cdr.objects.filter(start_date_time__gte=start_date, end_date_time__lte=end_date). \
        exclude(invoice__isnull=False).select_related('ocpi_master')
    params = ('ocpi_master', 'billed_to', 'currency')
    # Calculate the totals for each CPO/MSP pair
    # Using values_list() results in a list of tuples, which is more efficient than using values()
    result = queryset.values_list(*params).annotate(total=Sum('total_cost_incl_vat')).order_by(*params)
    # Convert the result to a list of InvoiceTotals
    return list(map(
        lambda x: InvoiceTotals(cpo=CredentialsRole.objects.get(pk=x[0]),
                                msp=CredentialsRole.objects.get(pk=x[1]),
                                currency=x[2], total=round(x[3], 2)),
        result))


def settle(start_datetime: Union[datetime, date], end_datetime: Union[datetime, date]) -> list[SettlementData]:
    """
    Calculate the settlements for the given time period.
    Create invoices and find the invoices that cancel each other out.
    @param start_datetime: Inclusive start date of the period
    @param end_datetime: Exclusive end date of the period
    @return: List of SettlementData objects, which show which parties are left with something to be paid
    """
    totals = calculate_invoice_totals(convert_to_utc_midnight(start_datetime), convert_to_utc_end_of_day(end_datetime))

    def company_credentials(party1: CredentialsRole, party2: CredentialsRole) -> Optional[Credentials]:
        """
        Check if the two parties represent the same company

        @param party1: The first party
        @param party2: The second party
        @return: The Credentials ID if the parties represent the same company, otherwise False
        """
        entities2 = get_entity_roles()
        for credentials_id, parties in entities2:
            if party1 in parties and party2 in parties:
                return Credentials.objects.get(pk=credentials_id)
        return None

    invoices = []

    from ocpi22 import logging

    for p1, p2 in combinations(totals, 2):
        company1 = company_credentials(p1.cpo, p2.msp)
        company2 = company_credentials(p1.msp, p2.cpo)
        if company1 and company2:
            if p1.total > p2.total:
                logging.info(f'INVOICING: {p1} bills {p2} {p1.total - p2.total} {p1.currency}')
                invoices.append(SettlementData(
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    amount=p1.total - p2.total,
                    currency=p1.currency,
                    who_bills=company1,
                    who_pays=company2,
                    totals=[p1, p2]
                ))
            elif p1.total <= p2.total:
                logging.info(f'INVOICING: {p2} bills {p1} {p2.total - p1.total} {p1.currency}')
                invoices.append(SettlementData(
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    amount=p2.total - p1.total,
                    currency=p1.currency,
                    who_bills=company2,
                    who_pays=company1,
                    totals=[p1, p2]
                ))
    # Remove the settled invoices from the invoices list
    [
        totals.remove(y)
        for x in invoices
        for y in x.totals
    ]

    # Create the SettlementData for the remaining invoices which have no corresponding opposite invoices
    for x in totals:
        try:
            logging.info(f'INVOICING: Invoice {x} has no pair, so it will be invoiced solo.')
            who_bills = x.cpo
            who_pays = x.msp
            assert who_bills.credentials
            assert who_pays.credentials

            invoices.append(SettlementData(
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                amount=x.total,
                currency=x.currency,
                who_bills=who_bills.credentials,
                who_pays=who_pays.credentials,
                totals=[x]
            ))
        except CredentialsRole.DoesNotExist as e:
            from ocpi22 import logging
            logging.error(f'*** {x} has no CredentialsRole for invoicing: {e}')
        except (ValueError, AssertionError) as e:
            from ocpi22 import logging
            logging.error(f'*** Unable to find Credentials for {x} to be able to invoice: {e}')
    return invoices
