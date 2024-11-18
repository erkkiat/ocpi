import requests


def send_sms(sender: str, msg_content: str, recipients: list):
    token = "-3XUbf2USb6AZFJL19XkZM8yVAUzHYts7U-VpbUr_wvg9bD7rZfAe1lZBpR1oDLk"

    payload = {
        "sender": sender,
        "message": msg_content,
        "recipients": [{"msisdn": recipient_number} for recipient_number in recipients],
    }

    resp = requests.post(
        "https://gatewayapi.com/rest/mtsms",
        json=payload,
        auth=(token, ""),
        timeout=10,
    )

    resp.raise_for_status()


def message_user(phone, charger_name, price, url):
    data = (
        f'Please approve charging at "{charger_name}". '
        f'The price is {price}. Respond "Ok" to start charging, '
        f'"cancel" to decline or "report" if you suspect fraud. '
        f"For real-time charging status, go to <URL>."
    )

    send_sms("ChargerHub.EU", data, ["+358405480238"])
