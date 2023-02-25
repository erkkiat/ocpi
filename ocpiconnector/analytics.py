import os
from decimal import Decimal

import requests

from ocpi22 import logging as logging
from ocpi22.models.session import Session

zoined_token = os.environ.get('ZOINED_TOKEN')


def send_update_to_analytics(session: Session):
    if not session.total_cost_incl_vat:
        logging.info(f'No total cost for session {session.uid} => no update to analytics')
        return
    if not zoined_token:
        logging.info(f'No Zoined token set => no update to analytics')
        return
    session_date = session.start_date_time.strftime('%Y-%m-%d')
    session_time = session.start_date_time.strftime('%H:%M:%S')
    data = [
        {
            "transaction_id": session.uid,
            "line_item_id": "1",
            "delivery_customer_id": session.cdr_token_uid,
            "sales_date": session_date,
            "sales_time": session_time,
            "product_id": session.evse.evse_id,
            "product_quantity": session.kwh,
            "product_unit_price": Decimal(session.total_cost_incl_vat) / session.kwh,
            "sales_value": session.total_cost_incl_vat,
            "sales_value_wo_vat": session.total_cost_excl_vat,
            "organisation_id": "1",
            "sales_currency": session.connector.tariff_ids.first().currency,
            "supplier_id": session.billed_to,
            # "purchase_price": 6.00,
            # "purchase_price_wo_vat": 5.00,
            # "purchase_currency": "EUR",
            "source_system": "ChargerHub OCPI Connector"
        }
    ]
    headers = {'content-type': 'application/json', 'Authorization': f'Bearer {zoined_token}'}
    # Todo: Async send
    response = requests.post(url="https://api.zoined.com/sales", json=data, headers=headers, timeout=5)
    if response.status_code != 200:
        logging.error(f'Unable to send update to analytics: {response.text}')
    else:
        logging.info(f'Update sent to analytics: {response.text}')
