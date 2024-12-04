from decimal import Decimal

from django.conf import settings

from ocpi22.models.session import Session
import ocpi22.tasks as tasks


def send_session_update_to_analytics(session: Session):
    if not settings.SEND_UPDATES or not tasks.zoined_token:
        return

    if hasattr(session, "analytics_sent"):
        # logging.info(f'Session {session.uid} already sent to analytics => no update')
        return
    if not session.total_cost_incl_vat:
        # logging.info(f'No total cost for session {session.uid} => no update to analytics')
        return
    if not session.connector.tariff_ids.exists():
        # logging.info(f'No tariff for session {session.uid} => no update to analytics')
        return
    session_date = session.start_date_time.strftime("%Y-%m-%d")
    session_time = session.start_date_time.strftime("%H:%M:%S")
    # getcontext().prec = 3  # Maybe better not to touch the precision
    data = {
        "transaction_id": session.uid,
        "line_item_id": "1",
        "delivery_customer_id": session.cdr_token_uid,
        "sales_date": session_date,
        "sales_time": session_time,
        "product_id": f"{session.connector.power_str()} {session.connector.get_standard_display()}",
        "product_quantity": session.kwh,
        "product_unit_price": Decimal(session.total_cost_incl_vat)
        / Decimal(max(session.kwh, 0.001)),
        "sales_value": session.total_cost_incl_vat,
        "sales_value_wo_vat": session.total_cost_excl_vat,
        "organisation_id": session.evse.uid,
        "organisation_group": session.location.uid,
        "custom_dimension1": session.location.name,
        "custom_dimension2": session.location.address,
        "custom_dimension3": session.location.postal_code,
        "custom_dimension4": session.location.city,
        "custom_dimension5": session.location.get_country_display(),
        "latitude": session.location.latitude,
        "longitude": session.location.longitude,
        "sales_currency": session.connector.tariff_ids.first().currency,
        "supplier_id": session.billed_to,
        # "purchase_price": 6.00,
        # "purchase_price_wo_vat": 5.00,
        # "purchase_currency": "EUR",
        "source_system": "SolidRoam Roaming Module",
    }

    # Send data to analytics
    tasks.send_data_to_analytics.delay(data, "https://api.zoined.com/sales")
    session.analytics_sent = True
