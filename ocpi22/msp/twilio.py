import ocpi22.logging as logging

from django.conf import settings
from twilio.rest import Client


def message_user(body, phone, *_args, **kwargs):
    if settings.TWILIO_API_KEY:
        account_sid, auth_token = settings.TWILIO_API_KEY.split(":")
        client = Client(account_sid, auth_token)

        message = client.messages.create(
            from_="whatsapp:+14155238886",
            body=body.format(**kwargs),
            to=f"whatsapp:{phone}",
            provide_feedback=True,
        )

        if not message:
            parameters = ", ".join(
                [f"{key} = {value}" for key, value in kwargs.items()]
            )
            logging.error(f"Unable to send whatsapp message: {parameters}")
