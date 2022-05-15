from django.conf import settings
from icecream import ic
from twilio.rest import Client


def message_user(phone, charger_name, price, url):
    account_sid, auth_token = settings.TWILIO_API_KEY.split(':')
    ic(account_sid, auth_token, phone, charger_name, price, url)

    # data = dict(
    #     from_='whatsapp:+14155238886',
    #     body=f'Please approve charging at "{charger_name}". '
    #          f'The prices are: {price or "unknown"}. '
    #          f'Respond "Ok" to start charging, '
    #          f'"cancel" to decline or "report" if you suspect fraud. '
    #          f'For real-time charging status, go to {url}.',
    #     to=f'whatsapp:{phone}',
    # )
    # response = requests.post(
    #     url='https://api.twilio.com/2010-04-01/Accounts/AC733e63a649b237b3ed174acfbe478851/Messages.json',
    #     data=data,
    #     auth=(account_sid, auth_token)
    # )
    # ic(response, response.json())

    client = Client(account_sid, auth_token)

    message = client.messages.create(
        from_='whatsapp:+14155238886',
        body=f'Please approve charging at "{charger_name}". '
             f'The price is {price or "unknown"}. Respond "Ok" or click below to start charging, '
             f'"cancel" to decline or "report" if you suspect fraud. '
             f'To approve and see real-time charging status, go to {url}.',
        to=f'whatsapp:{phone}',
        provide_feedback=True
    )

    ic(message, message.sid)
