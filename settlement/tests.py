import doctest
from dataclasses import asdict
from datetime import timedelta, datetime

import pytz
import time_machine
from django.db.models import Min, Max, Sum
from django.test import TestCase
from django.utils.datetime_safe import date
from icecream import ic

from ocpi22.credentials.util import get_entity_roles
from ocpi22.models.cdr import Cdr
from ocpiconnector.testutil import compare_dicts_recursively, compare_lists_recursively
from settlement.calculate import calculate_invoice_totals, settle
from settlement.testutil import create_cdrs
from settlement.util import calculate_invoicing_periods, DateRange
from util import convert_to_utc_midnight, convert_to_utc_end_of_day


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('settlement.util'))
    return tests


faketime = datetime(2021, 10, 2, 12, 0, 0, tzinfo=pytz.utc)  # So that the CDRs are created for September AND October


class SettlementData:
    invoice_data_ranges = [
        {'amount': 12.4,
         'currency': 'EUR',
         'end_datetime': date(2021, 9, 30),
         'start_datetime': date(2021, 9, 1),
         'totals': [{'cpo': 'FI*C00 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M01 (EMSP)',
                     'total': 2.48},
                    {'cpo': 'FI*C01 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M00 (EMSP)',
                     'total': 14.88}],
         'who_bills': 'CPO #1 / MSP #1',
         'who_pays': 'CPO #0 / MSP #0'},
        {'amount': 12.4,
         'currency': 'EUR',
         'end_datetime': date(2021, 9, 30),
         'start_datetime': date(2021, 9, 1),
         'totals': [{'cpo': 'FI*C01 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M02 (EMSP)',
                     'total': 3.72},
                    {'cpo': 'FI*C02 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M01 (EMSP)',
                     'total': 16.12}],
         'who_bills': 'CPO #2 / MSP #2',
         'who_pays': 'CPO #1 / MSP #1'},
        {'amount': 4.96,
         'currency': 'EUR',
         'end_datetime': date(2021, 9, 30),
         'start_datetime': date(2021, 9, 1),
         'totals': [{'cpo': 'FI*C02 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M03 (EMSP)',
                     'total': 4.96}],
         'who_bills': 'CPO #2 / MSP #2',
         'who_pays': 'CPO #3 / MSP #3'},
        {'amount': 24.8,
         'currency': 'EUR',
         'end_datetime': date(2021, 10, 31),
         'start_datetime': date(2021, 10, 1),
         'totals': [{'cpo': 'FI*C00 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M01 (EMSP)',
                     'total': 1.24},
                    {'cpo': 'FI*C01 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M00 (EMSP)',
                     'total': 26.04}],
         'who_bills': 'CPO #1 / MSP #1',
         'who_pays': 'CPO #0 / MSP #0'},
        {'amount': 24.8,
         'currency': 'EUR',
         'end_datetime': date(2021, 10, 31),
         'start_datetime': date(2021, 10, 1),
         'totals': [{'cpo': 'FI*C01 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M02 (EMSP)',
                     'total': 3.72},
                    {'cpo': 'FI*C02 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M01 (EMSP)',
                     'total': 28.52}],
         'who_bills': 'CPO #2 / MSP #2',
         'who_pays': 'CPO #1 / MSP #1'},
        {'amount': 6.2,
         'currency': 'EUR',
         'end_datetime': date(2021, 10, 31),
         'start_datetime': date(2021, 10, 1),
         'totals': [{'cpo': 'FI*C02 (CPO)',
                     'currency': 'EUR',
                     'msp': 'FI*M03 (EMSP)',
                     'total': 6.2}],
         'who_bills': 'CPO #2 / MSP #2',
         'who_pays': 'CPO #3 / MSP #3'}
    ]



class SettlementTestCase(TestCase):
    fixtures = ['ocpi22/data/test-database-hub.json']

    @time_machine.travel(faketime, tick=False)
    def setUp(self):
        Cdr.objects.all().delete()
        create_cdrs(3, 3)

    @time_machine.travel(faketime, tick=False)
    def test_settlement(self):
        cdr_count = Cdr.objects.count()
        # print(f'{cdr_count} CDR records in database.')
        start_datetime = datetime.now(pytz.utc) - timedelta(days=30)
        end_datetime = datetime.now(pytz.utc)
        totals = calculate_invoice_totals(start_datetime, end_datetime)

        totals_data = [(x.cpo.pk, x.msp.pk, x.total, x.currency) for x in totals]
        self.assertEqual(
            totals_data,
            [
                (1000, 2001, 3.72, 'EUR'),
                (1001, 2000, 28.52, 'EUR'),
                (1001, 2002, 6.2, 'EUR'),
                (1002, 2001, 31.0, 'EUR'),
                (1002, 2003, 8.68, 'EUR')
            ]
        )

        # Find out which parties represent the same company to make the settlement
        get_entity_roles.cache_clear()
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
                (1000, [1000, 2000]),
                (1001, [1001, 2001]),
                (1002, [1002, 2002]),
                (1003, [1003, 2003])
            ]
        )

        invoices = settle(start_datetime, end_datetime)
        invoices_data = [
            (x.start_datetime, x.end_datetime, x.amount, x.currency, x.who_bills.pk, x.who_pays.pk)
            for x in invoices
        ]
        # ic(invoices, invoices_data)

        self.assertEqual(
            invoices_data,
            [
                (start_datetime, end_datetime, 37.2, 'EUR', 1001, 1000),
                (start_datetime, end_datetime, 37.2, 'EUR', 1002, 1001),
                (start_datetime, end_datetime, 11.16, 'EUR', 1002, 1003),
            ]
        )

    @time_machine.travel(faketime, tick=False)
    def test_invoice_date_ranges_and_settlement(self):
        result = Cdr.objects.filter(invoice__isnull=True).aggregate(Min('end_date_time'), Max('end_date_time'))
        start_datetime, end_datetime = result.values()
        dates = list(calculate_invoicing_periods(start_datetime, end_datetime, 1))
        self.assertEqual(dates, [DateRange(date(2021, 9, 27), date(2021, 10, 3))])

        dates = list(calculate_invoicing_periods(start_datetime, end_datetime, 4))
        self.assertEqual(dates, [
            DateRange(date(2021, 9, 1), date(2021, 9, 30)),
            DateRange(date(2021, 10, 1), date(2021, 10, 31))
        ])

        settlements = [settle(d.start, d.end) for d in dates]
        settlements_data = [asdict(x) for s in settlements for x in s]
        # ic(settlements_data)
        self.assertTrue(compare_lists_recursively(settlements_data, SettlementData.invoice_data_ranges))

        rechecked_totals = sum([i.get('total') for x in settlements_data for i in x['totals']])
        cdr_total_excl_vat, cdr_total_incl_vat = \
            Cdr.objects.aggregate(total_cost_excl_vat=Sum('total_cost_excl_vat'),
                                  total_cost_incl_vat=Sum('total_cost_incl_vat')).values()
        self.assertEqual(rechecked_totals, cdr_total_incl_vat, 'Something seems off with the totals')

        # ic(Cdr.objects.values('end_date_time', 'total_cost_excl_vat', 'total_cost_incl_vat'))
