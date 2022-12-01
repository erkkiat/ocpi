from django.contrib.auth.models import User
from django.http import HttpResponse
from django.utils.translation import gettext as _

from ocpi22 import logging
import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
import stripe
from rest_framework.reverse import reverse

from ocpi22.util import CURRENCY_CHOICES
from payment.models import Customer, Payment, PaymentStatusEnum, PaymentMethod

stripe.api_key = os.environ.get(
    'STRIPE_API_KEY',
    'sk_test_51KZ6t8BsWTl6iWOLgXMH6YeAcORsv4Xa9aIAQzUJ2yItL7tapaLPGdNjD6vYD7qp4uixKHSFsngv5WeUoXPwc9RE00vL4IYemQ'
)

options_message = f'Please see OPTIONS to learn what you can POST at this endpoint'

# Are we in production?
if not settings.DEBUG and 'test' in stripe.api_key:
    logging.error('**** Using a Stripe payments test key in production')


def payment_intent(amount, currency='eur', **kwargs):
    return stripe.PaymentIntent.create(
        amount=int(amount * 100),
        currency=currency,
        payment_method_types=["card"],
        **kwargs
    )


class ReservePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="The currency amount to be reserved from the user's payment method"
    )
    currency = serializers.ChoiceField(
        choices=CURRENCY_CHOICES,
        help_text="The currency of the reservation, must match the payment method's currency"
    )


class NoPaymentMethod(RuntimeError):
    pass


class StripePayments:
    @staticmethod
    def add_card(request):
        query = 'session_id={CHECKOUT_SESSION_ID}'
        if hasattr(request.user, 'payment_customer'):
            customer = request.user.payment_customer
        else:
            logging.info(f'Creating Stripe customer for "{request.user.email}"')
            stripe_customer = stripe.Customer.create(idempotency_key=str(request.user.pk))
            customer = Customer.objects.create(user=request.user, customer_id=stripe_customer.id)
            ic(stripe_customer, customer)
        success_url = request.build_absolute_uri(reverse("msp-payment-success"))
        cancel_url = request.build_absolute_uri(reverse("msp-payment-cancel"))
        params = dict(
            payment_method_types=['card'],
            mode='setup',
            customer=customer.customer_id,
            success_url=f'{success_url}?{query}',
            cancel_url=f'{cancel_url}',
        )
        # ic(params)
        session = stripe.checkout.Session.create(**params)
        result = dict(
            # id=session.id,
            redirect_url=session.url,
            success_url=success_url,
            cancel_url=cancel_url
        )
        # ic(result)
        return result

    @staticmethod
    def reserve(user: User, amount: float, currency: str,
                description: str = _('Payment for EV charging'), payment_method: PaymentMethod = None):
        ic(amount, currency, description, payment_method)
        customer = user.payment_customer
        if not payment_method:
            payment_method = customer.payment_methods.first()
        if not payment_method:
            raise NoPaymentMethod('Customer has no payment methods available')

        ic(customer, payment_method)
        pi = payment_intent(amount=amount, capture_method='manual', currency=currency,
                            payment_method=payment_method, customer=customer.customer_id,
                            confirm=True, description=description)
        ic(PaymentStatusEnum.RESERVED.value)
        payment = Payment.objects.create(session_id=pi.get('id'),
                                         payment_method=payment_method,
                                         status=PaymentStatusEnum.RESERVED.value,
                                         amount=amount,
                                         currency=currency
                                         )
        if not payment:
            logging.error(
                f'Reservation has been made, but cannot create Payment in local database for '
                f'user {user.pk} for amount {amount}: {pi.get("id")}'
            )
            return HttpResponse('Reservation was made, but storing it to local database failed. Capture will not work',
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        # ic(pi, payment)
        # payment_status = pi.get('status')
        # if payment_status == 'requires_confirmation':
        #     confirm = stripe.PaymentIntent.confirm(
        #         pi, payment_method=payment_method, receipt_email=user.email
        #     )
        #     ic(confirm)
        #     requires_action = confirm.get('requires_action')
        #     if requires_action:
        #         ic(requires_action, confirm.get('next_action'))
        #         captured = stripe.PaymentIntent.capture(pi, amount_to_capture=1500)
        #         ic(captured)
        # if payment_status == 'requires_capture':
        #     captured = stripe.PaymentIntent.capture(pi, amount_to_capture=1500)
        #     ic(captured)
        return HttpResponse('Reservation made for payment.', status=status.HTTP_200_OK)

    @staticmethod
    def capture(payment: Payment, amount: float):
        try:
            captured = stripe.PaymentIntent.capture(payment.session_id, amount_to_capture=amount)
            ic(captured)
            payment.status = PaymentStatusEnum.COMPLETED.value
            payment.save(update_fields=['status'])
            return HttpResponse('Payment captured.', status=status.HTTP_200_OK)
        except None:
            logging.error(f'Unable to capture payment {payment} for {amount} {payment.currency}')


payments = StripePayments()


class PaymentViewSet(viewsets.ViewSet):
    publicly_visible = True

    def get_serializer_class(self):
        if not hasattr(self, 'action_map'):
            return serializers.Serializer
        # ic(self.action_map['post'])
        serializer = dict(
            reserve_amount=ReservePaymentSerializer,
        ).get(self.action_map['post'], serializers.Serializer)
        return serializer

    def get_serializer(self):
        serializer = self.get_serializer_class()
        return serializer()

    def get_metadata_class(self):
        if not hasattr(self, 'action_map'):
            return serializers.Serializer
        # ic(self.action_map['post'])
        serializer = dict(
            reserve_amount=ReservePaymentSerializer,
        ).get(self.action_map['post'], ReservePaymentSerializer)
        return serializer

    def get_view_name(self):
        if hasattr(self, 'kwargs') and 'uid' in self.kwargs:
            return f'Payment {self.kwargs.get("uid")}'
        if self.name:
            return f'{self.name.capitalize()}'
        return f'Payments'

    @method_decorator(login_required)
    @action(methods=('GET', 'POST'), detail=False)
    def add_card(self, request):
        # query = 'session_id={CHECKOUT_SESSION_ID}'
        # if hasattr(request.user, 'payment_customer'):
        #     customer = request.user.payment_customer
        # else:
        #     logging.info(f'Creating Stripe customer for "{request.user.email}"')
        #     customer = stripe.Customer.create(idempotency_key=str(request.user.pk))
        #     Customer.objects.create(user=request.user, customer_id=customer.id)
        # ic(customer)
        # success_url = request.build_absolute_uri(reverse("msp-payment-success"))
        # cancel_url = request.build_absolute_uri(reverse("msp-payment-cancel"))
        # params = dict(
        #     payment_method_types=['card'],
        #     mode='setup',
        #     customer=customer.id,
        #     success_url=f'{success_url}?{query}',
        #     cancel_url=f'{cancel_url}',
        # )
        # ic(params)
        # session = stripe.checkout.Session.create(**params)
        # result = dict(
        #     id=session.id,
        #     redirect_url=session.url,
        #     success_url=success_url,
        #     cancel_url=cancel_url
        # )
        # ic(result)
        result = payments.add_card(request)
        return Response(result)

    @action(methods=('GET', 'POST'), detail=False)
    def success(self, request):
        try:
            # ic(request.GET)
            session_id = request.GET.get('session_id')
            if session_id:
                session = stripe.checkout.Session.retrieve(session_id)
                # ic(session)
                intent = session.get('setup_intent', '')
                if intent:
                    setup_intent = stripe.SetupIntent.retrieve(intent)
                    payment_method_id = setup_intent.get('payment_method')
                    customer_id = setup_intent.get('customer')
                    customer = Customer.objects.get(customer_id=customer_id)
                    payment_method = PaymentMethod.objects.create(payment_method_id=payment_method_id,
                                                                  customer=customer)
                    ic(payment_method_id, customer_id, customer, payment_method)
                    if len(request.user.payment_customer.payment_methods.all()):
                        logging.info(f'Payment method {payment_method_id} added for user {request.user.pk}')
                        ic(payment_method_id, request.user.pk, request.user.payment_customer.payment_methods.all())
                        return HttpResponse('The payment method has been added. Please wait to be redirected.',
                                            status=status.HTTP_200_OK)
                    else:
                        logging.error(f'Failed to add payment method for user {request.user.pk}', request)
                else:
                    logging.error(f'No payment intent received from Stripe for session {session_id}')
            else:
                logging.error(f'No session ID in request from Stripe')
        except stripe.error.InvalidRequestError as e:
            logging.error(f'Payment session does not exist at Stripe: {e}', request)
        except Customer.DoesNotExist as e:
            logging.error(f'PaymentCustomer does not exist: {e}')

        return HttpResponse('Adding a payment method failed', status=status.HTTP_400_BAD_REQUEST)

    @action(methods=('GET', 'POST'), detail=False)
    def cancel(self, request):
        ic(request.GET)
        session_id = request.GET.get('session_id')
        if session_id:
            payment = Payment.objects.get(session_id=session_id)
            payment.status = PaymentStatusEnum.ERROR.value
            payment.save(update_fields=['status'])
        return HttpResponse('')

    @action(methods=('GET', 'POST'), detail=False)
    def reserve_amount(self, request):
        """
        This call reserves an amount of currency from the logged in customer's payment method.

        ## Status codes

        * `HTTP_200_OK` when the payment reservation has been made successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_406_NOT_ACCEPTABLE` when the user has no payment methods specified
        """
        try:
            if request.method == 'GET':
                return Response(options_message, status=status.HTTP_400_BAD_REQUEST)

            serializer = ReservePaymentSerializer(data=request.data)
            if serializer.is_valid():
                payment_method = request.user.payment_customer.payment_methods.first()
                amount = float(serializer.validated_data.get("amount"))
                result = payments.reserve(user=request.user, payment_method=payment_method,
                                          amount=amount,
                                          currency=serializer.validated_data.get("currency"))
                ic(payment_method, result)
                return Response(
                    dict(
                        status_text=_('Reservation has been made successfully'),
                        amount=amount,
                        msp_user_id=request.user.pk,
                    )
                )
            else:
                ic(serializer.errors)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except User.payment_customer.RelatedObjectDoesNotExist as e:
            logging.error(f'Cannot make reservation for user {request.user.pk} without any payment methods added: {e}',
                          request)
            return Response(f'User has no payment methods specified: {e}', status=status.HTTP_406_NOT_ACCEPTABLE)

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None
