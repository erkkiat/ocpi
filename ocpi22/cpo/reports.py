from django.db.models import Sum
from slick_reporting.views import SlickReportView
from slick_reporting.fields import SlickReportField
from ..models.cdr import Cdr


# from django import forms
# from slick_reporting.form_factory import BaseReportForm


# class ChargingSessionsReportForm(BaseReportForm, forms.ModelForm):
#     class Meta:
#         model = Cdr
#         fields = ['billed_to']
#
#     foreign_keys = []
#     crosstab_model = Cdr
#
#     # base_fields = dict(
#     #     items=['billed_to'],
#     #     disabled=[],
#     # )
#
#     # billed_to = forms.CharField()
#
#     def get_filters(self):
#         return None, None


class ChargingSessionsReport(SlickReportView):
    report_model = Cdr
    # form_class = ChargingSessionsReportForm
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
            'plot_total': True,
            'title_source': 'billed_to',
            'title': 'Total revenue',
        },
    ]
