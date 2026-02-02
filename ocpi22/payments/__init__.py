"""
EVRF DirectPayment Module

This module implements the DirectPayment OCPI 2.2.1 extension from EV Roaming Foundation.
It supports direct payment at EV charging stations via payment terminals (e.g., Payter).

This is a namespace module within ocpi22, NOT a separate Django app.
Models are registered under the ocpi22 app.

Reference: DirectPayment_2_2_1___EVRF_version.pdf (March 2024)
"""

from ocpi22.payments.models import Terminal, InvoiceCreatorEnum

__all__ = [
    "Terminal",
    "InvoiceCreatorEnum",
]
