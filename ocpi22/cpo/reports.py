from django.db.models import Sum
from slick_reporting.views import SlickReportView
from slick_reporting.fields import SlickReportField
from ..models.cdr import Cdr


class ChargingSessionsReport(SlickReportView):
    report_model = Cdr
    date_field = 'start_date_time'
    group_by = 'billed_to'
    columns = [
        'billed_to',
        SlickReportField.create(Sum, 'total_energy', name='sum__total_energy'),
        SlickReportField.create(Sum, 'total_cost_excl_vat', name='sum__total_cost_excl_vat'),
    ]

    chart_settings = [
        {
            'type': 'column',
            'data_source': ['sum__total_cost_excl_vat'],
            'plot_total': False,
            'title_source': 'billed_to',
            'title': 'Total income',
        },
    ]
