import doctest
from dataclasses import dataclass, field
from datetime import date, timedelta, datetime, timezone, time
from itertools import chain, groupby, combinations
from typing import Optional

import pytz
import time_machine
from django.db.models import Sum, Prefetch
from django.test import TestCase
from icecream import ic

from ocpi22.choices import OcpiRolesEnum, TokenType
from ocpi22.models.cdr import Cdr
from ocpi22.models.credentials import Credentials, CredentialsRole
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpi22.ocpi.auth import get_credentialsrole
from ocpiconnector.ocpi_identities import create_credentialsrole, Party
from util import DistributedCache


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('settlement.util'))
    return tests


def create_cdrs():
    # Create a number of parties and plenty of CDR records between them
    number_of_parties = 3
    days = 3

    # Create the Credentials
    credentials = [Credentials.objects.create() for x in range(0, number_of_parties+1)]

    # Create the CredentialsRoles for the CPOs and MSPs
    cpo = [create_credentialsrole(Party('FI', f'C{x:02d}'), business_name=f'CPO #{x}', role=OcpiRolesEnum.CPO,
                                  credentials=credentials[x])
           for x in range(0, number_of_parties+1)]
    msp = [create_credentialsrole(Party('FI', f'M{x:02d}'), business_name=f'MSP #{x}', role=OcpiRolesEnum.EMSP,
                                  credentials=credentials[x])
           for x in range(0, number_of_parties+1)]

    # Create roaming agreements between the CPOs and MSPs
    for i in range(0, number_of_parties):
        cpo[i].agreed_parties.add(msp[i+1])
        cpo[i+1].agreed_parties.add(msp[i])

    test_data_1 = (
        (number_of_parties * n + i, date.today() - timedelta(days=n), cpo[i], msp[i + 1], n+i)
        for i in range(0, number_of_parties)
        for n in range(1, days)
    )
    test_data_2 = (
        (10000 + number_of_parties * n + i, date.today() - timedelta(days=n), cpo[i + 1], msp[i], n+i+10)
        for i in range(0, number_of_parties-1)  # Leave out the last one on purpose to create an invoice with no pair
        for n in range(1, days)
    )
    combined_data = chain.from_iterable([test_data_1, test_data_2])

    def proxy(*args):
        create_cdr(*args[0])

    list(map(proxy, combined_data))


def create_cdr(number: int, d: date, cpo, msp, cost, currency='EUR', energy=50.0, duration=60.0) -> Credentials:
    start_date_time = datetime.combine(d, time(18, 0)).replace(tzinfo=timezone.utc)
    end_date_time = start_date_time + timedelta(minutes=duration)
    evse = Evse.objects.first()
    location = evse.location
    connector = evse.connectors.first()
    credentials = Credentials.objects.first()

    # ic(str(cpo), str(msp), cost, currency)

    return Cdr.objects.create(
        ocpi_master=cpo,
        start_date_time=start_date_time,
        end_date_time=end_date_time,
        billed_to=str(msp.party),
        uid=f'CDR-{number}',
        session_id=f'SESSION-{number}',
        internal_reference=f'REFERENCE-{number}',
        cdr_token_uid='TOKEN1',
        cdr_token_type=TokenType.RFID,
        cdr_token_contract_id='12345',
        auth_method=Session.AUTH_REQUEST,
        authorization_reference=f'AUTH-{number}',
        cdr_location_id=location.uid,
        cdr_location_address=location.address,
        cdr_location_name=location.name,
        cdr_location_city=location.city,
        cdr_location_postal_code=location.postal_code or '-',
        cdr_location_country=location.country,

        # Make sure coordinates have 6 decimals
        cdr_location_latitude=f'{float(location.latitude):.6f}',
        cdr_location_longitude=f'{float(location.longitude):.6f}',

        cdr_location_evse_uid=evse.uid,
        cdr_location_evse_id=evse.evse_id,
        cdr_location_connector_id=connector.uid,
        cdr_location_connector_standard=connector.standard,
        cdr_location_connector_format=connector.format,
        cdr_location_connector_power_type=connector.power_type,
        currency=currency,
        total_cost_excl_vat=cost,
        total_cost_incl_vat=cost*1.24,
        total_energy=energy,
        credentials=credentials,
        last_updated=datetime.now(pytz.utc),
    )


@DistributedCache(expiration=60*30)  # 30 minutes cache
def get_entity_party_ids() -> list[list[str]]:
    """
    Get the party IDs of the entities that represent the same company

    @return: A list of lists of party IDs, which each top level list represents a company (based on Credentials)
    """
    queryset = Credentials.objects.prefetch_related(
        Prefetch('roles', queryset=CredentialsRole.objects.order_by('country_code', 'party_id'))
    ).order_by('id').values_list('id', 'roles__country_code', 'roles__party_id')
    # We have now [(2, 'FI', 'CP1'), (2, 'FI', 'MSP'), (2, 'FI', 'NAP'), (3, 'FI', 'HUB'), ... ]
    # We want to group by the first element (Credentials.pk)
    result = (
        (a, list(b))
        for a, b in groupby(queryset, lambda x: x[0])
    )
    # Then remove the Credentials.pk from the result since we only need the lists of party IDs
    result = [
        (a, list(map(lambda x: Party(x[1], x[2]), b)))
        for a, b in result
    ]
    # Now we have [(2, ['FI*CP1', 'FI*MSP', 'FI*NAP']), (3, ['FI*HUB']), ... ]
    return result


@DistributedCache(expiration=60*30)  # 30 minutes cache
def get_entity_roles() -> list[list[str]]:
    """
    Get the party IDs of the entities that represent the same company

    @return: A list of lists of party IDs, which each top level list represents a company (based on Credentials)
    """
    queryset = Credentials.objects.prefetch_related(
        Prefetch('roles', queryset=CredentialsRole.objects.order_by('country_code', 'party_id'))
    ).order_by('id').values_list('id', 'roles')
    # We have now [(2, 'FI', 'CP1'), (2, 'FI', 'MSP'), (2, 'FI', 'NAP'), (3, 'FI', 'HUB'), ... ]
    # We want to group by the first element (Credentials.pk)
    result = (
        (a, list(b))
        for a, b in groupby(queryset, lambda x: x[0])
    )
    # Then remove the Credentials.pk from the result since we only need the lists of party IDs
    result = [
        (a, list(map(lambda x: CredentialsRole.objects.get(pk=x[1]), b)))
        for a, b in result
    ]
    # Now we have [(2, ['FI*CP1', 'FI*MSP', 'FI*NAP']), (3, ['FI*HUB']), ... ]
    return result


faketime = datetime(2021, 10, 1, 12, 0, 0, tzinfo=pytz.utc)


class SettlementTestCase(TestCase):
    fixtures = ['ocpi22/data/test-database-hub.json']

    @time_machine.travel(faketime, tick=False)
    def setUp(self):
        create_cdrs()

    @time_machine.travel(faketime, tick=False)
    def test_invoice_creation(self):
        cdr_count = Cdr.objects.count()
        print(f'{cdr_count} CDR records in database.')
        start_datetime = datetime.now(pytz.utc) - timedelta(days=30)
        end_datetime = datetime.now(pytz.utc)
        totals = calculate_invoice_totals(start_datetime, end_datetime)

        totals_data = [(x.cpo.pk, x.msp.pk, x.total, x.currency) for x in totals]
        self.assertEqual(
            totals_data,
            [
                (82, 87, 3.72, 'EUR'),
                (83, 86, 28.52, 'EUR'),
                (83, 88, 6.2, 'EUR'),
                (84, 87, 31.0, 'EUR'),
                (84, 89, 8.68, 'EUR')
            ]
        )

        # Find out which parties represent the same company to make the settlement
        get_entity_party_ids.cache_clear()
        entities = get_entity_roles()
        # ic(entities)
        entities_data = [(c, list(map(lambda x: x.pk, e))) for c, e in entities]

        self.assertEqual(
            entities_data,
            [
                (2, [3, 4, 5]),
                (3, [6]),
                (9, [9]),
                (81, [81]),
                (82, [82, 86]),
                (83, [83, 87]),
                (84, [84, 88]),
                (85, [85, 89])
            ]
        )

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
                # print(f'*** {p1} and {p2} are reciprocal')
                if p1.total > p2.total:
                    logging.info(f'*** {p1} bills {p2} {p1.total - p2.total} {p1.currency}')
                    invoices.append(Invoice(
                        start_datetime=start_datetime,
                        end_datetime=end_datetime,
                        amount=p1.total - p2.total,
                        currency=p1.currency,
                        who_bills=company1,
                        who_pays=company2,
                        totals=[p1, p2]
                    ))
                elif p1.total <= p2.total:
                    logging.info(f'*** {p2} bills {p1} {p2.total - p1.total} {p1.currency}')
                    invoices.append(Invoice(
                        start_datetime=start_datetime,
                        end_datetime=end_datetime,
                        amount=p2.total - p1.total,
                        currency=p1.currency,
                        who_bills=company2,
                        who_pays=company1,
                        totals=[p1, p2]
                    ))
        [
            totals.remove(y)
            for x in invoices
            for y in x.totals
        ]
        self.assertEqual(len(totals), 1, 'There should be one solo invoicing line remaining with no settlement pair')
        for x in totals:
            try:
                logging.info(f'Invoice {x} has no pair, so it will be invoiced solo.')
                who_bills = x.cpo
                who_pays = x.msp
                assert who_bills.credentials
                assert who_pays.credentials

                invoices.append(Invoice(
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
                raise
                from ocpi22 import logging
                logging.error(f'*** Unable to find Credentials for {x} to be able to invoice: {e}')
        invoices_data = [
            (x.start_datetime, x.end_datetime, x.amount, x.currency, x.who_bills.pk, x.who_pays.pk)
            for x in invoices
        ]
        # ic(invoices, invoices_data)

        self.assertEqual(
            invoices_data,
            [
                (start_datetime, end_datetime, 24.8, 'EUR', 83, 82),
                (start_datetime, end_datetime, 24.8, 'EUR', 84, 83),
                (start_datetime, end_datetime, 8.68, 'EUR', 84, 85),
            ]
        )


@dataclass
class InvoiceTotals:
    cpo: CredentialsRole
    msp: CredentialsRole
    total: float
    currency: str


@dataclass
class Invoice:
    start_datetime: datetime
    end_datetime: datetime
    amount: float
    currency: str
    who_bills: Credentials
    who_pays: Credentials
    totals: list[InvoiceTotals] = field(default_factory=list)


def calculate_invoice_totals(start_date: datetime, end_date: datetime):
    """
    Find all the CPOs who need to invoice one or more MSPs during the given time period.

    @param start_date: Start date of the period
    @param end_date: End date of the period
    @return: A list of pairs (CPO, MSP)
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
                                msp=get_credentialsrole(party=Party(*x[1].split('*')), create=True),
                                currency=x[2], total=round(x[3], 2)),
        result))
