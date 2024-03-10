import doctest
from datetime import timedelta, datetime

import pytz
import time_machine
from django.test import TestCase

from ocpi22.credentials.util import get_entity_roles
from ocpi22.models.cdr import Cdr
from settlement.calculate import calculate_invoice_totals, settle
from settlement.testutil import create_cdrs


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('settlement.util'))
    return tests


faketime = datetime(2021, 10, 1, 12, 0, 0, tzinfo=pytz.utc)


class SettlementTestCase(TestCase):
    fixtures = ['ocpi22/data/test-database-hub.json']

    @time_machine.travel(faketime, tick=False)
    def setUp(self):
        Cdr.objects.all().delete()
        create_cdrs(3, 3)

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
                (start_datetime, end_datetime, 24.8, 'EUR', 1001, 1000),
                (start_datetime, end_datetime, 24.8, 'EUR', 1002, 1001),
                (start_datetime, end_datetime, 8.68, 'EUR', 1002, 1003),
            ]
        )
