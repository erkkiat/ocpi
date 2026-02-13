"""
EVRF DirectPayment Module URL Configuration

URL patterns for Terminal and FinancialAdviceConfirmation endpoints.
Implements EVRF DirectPayment OCPI 2.2.1 extension specification.

Reference: DirectPayment_2_2_1___EVRF_version.pdf (March 2024)
"""

from django.urls import path

from ocpi22.payments.api import TerminalViewSet, FinancialAdviceConfirmationViewSet

urlpatterns = [
    # Terminals
    path(
        "terminals/",
        TerminalViewSet.as_view({"get": "list", "post": "post"}),
        name="terminal-list",
    ),
    path(
        "terminals/<str:terminal_id>",
        TerminalViewSet.as_view({"get": "get", "put": "put", "patch": "patch"}),
        name="terminal-detail",
    ),
    # Financial Advice Confirmations
    path(
        "financial-advice-confirmations/",
        FinancialAdviceConfirmationViewSet.as_view({"get": "list", "post": "post"}),
        name="fac-list",
    ),
    path(
        "financial-advice-confirmations/<str:fac_id>",
        FinancialAdviceConfirmationViewSet.as_view({"get": "get"}),
        name="fac-detail",
    ),
]
