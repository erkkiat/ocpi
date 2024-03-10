from django.urls import path

from settlement.views import InvoiceReportViews

urlpatterns = [
    path('invoice/',
         InvoiceReportViews.as_view({'get': 'session_list'}),
         name='invoice-list'),
]
