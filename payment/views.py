from logging import getLogger
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _


import os

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
import stripe
from util import reverse

from ocpi22.models.cdr import Cdr
from ocpi22.util import CURRENCY_CHOICES
from payment.models import Customer, Payment, PaymentStatusEnum, PaymentMethod

logger = getLogger(__name__)

stripe.api_key = os.environ.get(
    "STRIPE_API_KEY",
    "sk_test_51KZ6t8BsWTl6iWOLgXMH6YeAcORsv4Xa9aIAQzUJ2yItL7tapaLPGdNjD6vYD7qp4uixKHSFsngv5WeUoXPwc9RE00vL4IYemQ",
)

options_message = "Please see OPTIONS to learn what you can POST at this endpoint"


def payment_intent(amount, currency="eur", **kwargs):
    return stripe.PaymentIntent.create(
        amount=int(amount * 100),
        currency=currency,
        payment_method_types=["card"],
        **kwargs,
    )


class ReservePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="The currency amount to be reserved from the user's payment method",
    )
    currency = serializers.ChoiceField(
        choices=CURRENCY_CHOICES,
        help_text="The currency of the reservation, must match the payment method's currency",
    )


class NoPaymentMethod(RuntimeError):
    pass


class StripePayments:
    @staticmethod
    def add_card(request):
        query = "session_id={CHECKOUT_SESSION_ID}"
        if hasattr(request.user, "payment_customer"):
            customer = request.user.payment_customer
        else:
            logger.info(f'Creating Stripe customer for "{request.user.email}"')
            stripe_customer = stripe.Customer.create(
                idempotency_key=str(request.user.pk)
            )
            customer = Customer.objects.create(
                user=request.user, customer_id=stripe_customer.id
            )
        success_url = request.build_absolute_uri(reverse("msp-payment-success"))
        cancel_url = request.build_absolute_uri(reverse("msp-payment-cancel"))
        params = dict(
            payment_method_types=["card"],
            mode="setup",
            customer=customer.customer_id,
            success_url=f"{success_url}?{query}",
            cancel_url=f"{cancel_url}",
        )
        session = stripe.checkout.Session.create(**params)
        result = dict(
            # id=session.id,
            redirect_url=session.url,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return result

    @staticmethod
    def reserve(
        user: User,
        amount: float,
        currency: str,
        description: str = _("Payment for EV charging"),
        payment_method: PaymentMethod = None,
    ):
        customer = user.payment_customer
        if not payment_method:
            payment_method = customer.payment_methods.first()
        if not payment_method:
            raise NoPaymentMethod("Customer has no payment methods available")

        pi = payment_intent(
            amount=amount,
            capture_method="manual",
            currency=currency,
            payment_method=payment_method,
            customer=customer.customer_id,
            confirm=True,
            description=description,
        )

        payment = Payment.objects.create(
            session_id=pi.get("id"),
            payment_method=payment_method,
            status=PaymentStatusEnum.RESERVED.value,
            amount=amount,
            currency=currency,
        )
        if not payment:
            logger.error(
                f"Reservation has been made, but cannot create Payment in local database for "
                f"user {user.pk} for amount {amount}: {pi.get('id')}"
            )
            return HttpResponse(
                "Reservation was made, but storing it to local database failed. Capture will not work",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # payment_status = pi.get('status')
        # if payment_status == 'requires_confirmation':
        #     confirm = stripe.PaymentIntent.confirm(
        #         pi, payment_method=payment_method, receipt_email=user.email
        #     )
        #
        #     requires_action = confirm.get('requires_action')
        #     if requires_action:
        #
        #         captured = stripe.PaymentIntent.capture(pi, amount_to_capture=1500)
        #
        # if payment_status == 'requires_capture':
        #     captured = stripe.PaymentIntent.capture(pi, amount_to_capture=1500)
        #
        return HttpResponse("Reservation made for payment.", status=status.HTTP_200_OK)

    @staticmethod
    def capture(payment: Payment, amount: float):
        try:
            stripe.PaymentIntent.capture(payment.session_id, amount_to_capture=amount)

            payment.status = PaymentStatusEnum.COMPLETED.value
            payment.save(update_fields=["status"])
            return HttpResponse("Payment captured.", status=status.HTTP_200_OK)
        except None:
            logger.error(
                f"Unable to capture payment {payment} for {amount} {payment.currency}"
            )


payments = StripePayments()


class PaymentViewSet(viewsets.ViewSet):
    publicly_visible = True

    def get_serializer_class(self):
        if not hasattr(self, "action_map"):
            return serializers.Serializer

        serializer = dict(
            reserve_amount=ReservePaymentSerializer,
        ).get(self.action_map["post"], serializers.Serializer)
        return serializer

    def get_serializer(self):
        serializer = self.get_serializer_class()
        return serializer()

    def get_metadata_class(self):
        if not hasattr(self, "action_map"):
            return serializers.Serializer

        serializer = dict(
            reserve_amount=ReservePaymentSerializer,
        ).get(self.action_map["post"], ReservePaymentSerializer)
        return serializer

    def get_view_name(self):
        if hasattr(self, "kwargs") and "uid" in self.kwargs:
            return f"Payment {self.kwargs.get('uid')}"
        if self.name:
            return f"{self.name.capitalize()}"
        return "Payments"

    @method_decorator(login_required)
    @action(methods=("GET", "POST"), detail=False)
    def add_card(self, request):
        # query = 'session_id={CHECKOUT_SESSION_ID}'
        # if hasattr(request.user, 'payment_customer'):
        #     customer = request.user.payment_customer
        # else:
        #     logger.info(f'Creating Stripe customer for "{request.user.email}"')
        #     customer = stripe.Customer.create(idempotency_key=str(request.user.pk))
        #     Customer.objects.create(user=request.user, customer_id=customer.id)

        # success_url = request.build_absolute_uri(reverse("msp-payment-success"))
        # cancel_url = request.build_absolute_uri(reverse("msp-payment-cancel"))
        # params = dict(
        #     payment_method_types=['card'],
        #     mode='setup',
        #     customer=customer.id,
        #     success_url=f'{success_url}?{query}',
        #     cancel_url=f'{cancel_url}',
        # )

        # session = stripe.checkout.Session.create(**params)
        # result = dict(
        #     id=session.id,
        #     redirect_url=session.url,
        #     success_url=success_url,
        #     cancel_url=cancel_url
        # )

        result = payments.add_card(request)
        return Response(result)

    @action(methods=("GET", "POST"), detail=False)
    def success(self, request):
        try:
            session_id = request.GET.get("session_id")
            if session_id:
                session = stripe.checkout.Session.retrieve(session_id)

                intent = session.get("setup_intent", "")
                if intent:
                    setup_intent = stripe.SetupIntent.retrieve(intent)
                    payment_method_id = setup_intent.get("payment_method")
                    customer_id = setup_intent.get("customer")
                    customer = Customer.objects.get(customer_id=customer_id)
                    PaymentMethod.objects.create(
                        payment_method_id=payment_method_id, customer=customer
                    )

                    if len(request.user.payment_customer.payment_methods.all()):
                        logger.info(
                            f"Payment method {payment_method_id} added for user {request.user.pk}"
                        )

                        return HttpResponse(
                            "The payment method has been added. Please wait to be redirected.",
                            status=status.HTTP_200_OK,
                        )
                    else:
                        logger.error(
                            f"Failed to add payment method for user {request.user.pk}",
                            request,
                        )
                else:
                    logger.error(
                        f"No payment intent received from Stripe for session {session_id}"
                    )
            else:
                logger.error("No session ID in request from Stripe")
        except stripe.error.InvalidRequestError:
            logger.exception("Payment session does not exist at Stripe")
        except Customer.DoesNotExist:
            logger.exception("PaymentCustomer does not exist")

        return HttpResponse(
            "Adding a payment method failed", status=status.HTTP_400_BAD_REQUEST
        )

    @action(methods=("GET", "POST"), detail=False)
    def cancel(self, request):
        session_id = request.GET.get("session_id")
        if session_id:
            payment = Payment.objects.get(session_id=session_id)
            payment.status = PaymentStatusEnum.ERROR.value
            payment.save(update_fields=["status"])
        return HttpResponse("")

    @action(methods=("GET", "POST"), detail=False)
    def reserve_amount(self, request):
        """
        This call reserves an amount of currency from the logged in customer's payment method.

        ## Status codes

        * `HTTP_200_OK` when the payment reservation has been made successfully
        * `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
        * `HTTP_406_NOT_ACCEPTABLE` when the user has no payment methods specified
        """
        try:
            if request.method == "GET":
                return Response(options_message, status=status.HTTP_400_BAD_REQUEST)

            serializer = ReservePaymentSerializer(data=request.data)
            if serializer.is_valid():
                payment_method: PaymentMethod = (
                    request.user.payment_customer.payment_methods.first()
                )
                amount = float(serializer.validated_data.get("amount"))
                payments.reserve(
                    user=request.user,
                    payment_method=payment_method,
                    amount=amount,
                    currency=serializer.validated_data.get("currency"),
                )

                return Response(
                    dict(
                        status_text=_("Reservation has been made successfully"),
                        amount=amount,
                        msp_user_id=request.user.pk,
                        payment_method_id=payment_method.payment_method_id,
                    )
                )
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except User.payment_customer.RelatedObjectDoesNotExist:
            logger.exception(
                f"Cannot make reservation for user {request.user.pk} without any payment methods added",
            )
            return Response(
                "User has no payment methods specified",
                status=status.HTTP_406_NOT_ACCEPTABLE,
            )

    @staticmethod
    def get_object(uid=None) -> None:
        # Needed for OPTIONS to work in list view
        return None


def capture_reservation(cdr: Cdr) -> bool:
    # Lisää Paymentiin authorization_reference
    session = cdr.session
    amount = cdr.total_cost_incl_vat
    payment = cdr.session.payment
    if session and payment and amount:
        payments.capture(payment, amount)
        return True
    else:
        logger.error(
            f"No session in the CDR, cannot capture amount {amount} for payment {payment}"
        )
    return False


# Todo: Step by step guidance with actual links and current data
# Todo: Cover reservations and transactions made outside of the system
# Todo: Admin log for transactions, connection issues, pulls, pushes
