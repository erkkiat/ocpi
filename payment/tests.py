import os
from datetime import datetime
from unittest.mock import patch, Mock

import stripe
from django.contrib.auth.models import User
from django.test import TestCase
from icecream import ic
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from payment import test_data
from payment.models import Customer, Payment
from payment.views import PaymentViewSet, StripePayments

faketime = datetime(2022, 1, 1, 12, 0)
dirname = os.path.dirname(os.path.abspath(__file__))
api_factory = APIRequestFactory()

ic.includeContext = True


class PaymentTests(TestCase):
    def setUp(self) -> None:
        self.testuser = User.objects.create_user('test', 'test@anon.example.com')

    def test_add_card(self):
        try:
            url = reverse('msp-payment-add-card')

            request = api_factory.post(url)
            request.data = {}
            request.user = self.testuser

            response = PaymentViewSet().add_card(request)
            data = response.data
            self.assertIn('redirect_url', data, 'Stripe response is missing "redirect_url"')
            self.assertIn('success_url', data, 'Stripe response is missing "success_url"')
            self.assertIn('cancel_url', data, 'Stripe response is missing "cancel_url"')
        except stripe.error.APIConnectionError as e:
            self.skipTest(f'*** Cannot connect to Stripe, continuing with offline tests: {e}')

    @patch('stripe.PaymentIntent.capture', return_value=test_data.captured)
    @patch('stripe.PaymentIntent.create', return_value=test_data.payment_intent)
    @patch('stripe.SetupIntent.retrieve', return_value=test_data.setup_intent)
    @patch('stripe.checkout.Session.retrieve', return_value=test_data.session)
    def test_add_card_success(self,
                              session_retrieve_mock: Mock,
                              setupintent_retrieve_mock: Mock,
                              paymentintent_create_mock: Mock,
                              paymentintent_capture_mock: Mock,
                              ):
        url = reverse('msp-payment-success')

        request = api_factory.post(url)
        request.data = {}
        request.user = self.testuser

        # First without Session ID
        response = PaymentViewSet().success(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # With Session ID
        session_id = test_data.session.get('id')
        ic(session_id)
        request = api_factory.get(f'url?session_id={session_id}')
        request.user = self.testuser
        Customer.objects.create(user=request.user, customer_id='cus_MpaqQOHTYhC7q4')

        response = PaymentViewSet().success(request)

        assert len(request.user.payment_customer.payment_methods.all()), \
            'Payment methods seem to not been added successfully'

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        session_retrieve_mock.assert_called_once_with(session_id)
        setupintent_retrieve_mock.assert_called_once()

        #
        # Make a reservation on the credit card
        #

        url = reverse('msp-payment-reserve-amount')

        # Wrong format for data

        request = api_factory.post(url)
        request.data = dict(amount="abc", currency=123)
        request.user = self.testuser

        ic(request.user, request.user.payment_customer.payment_methods.all())

        response = PaymentViewSet().reserve_amount(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, 'Expecting payment reservation to fail')

        request = api_factory.post(url)
        request.data = dict(amount=123, currency='EUR')
        request.user = self.testuser

        ic(request.user, request.user.payment_customer.payment_methods.all())

        response = PaymentViewSet().reserve_amount(request)

        self.assertTrue(response, 'There is no response from the payments reserve() endpoint')
        ic(response, response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, 'Expecting payment reservation to succeed')
        paymentintent_create_mock.assert_called_once()

        payments = StripePayments()

        payment_method = self.testuser.payment_customer.payment_methods.first()

        payment = Payment.objects.get(payment_method=payment_method)
        result = payments.capture(payment, 3.14)
        ic(result)

        paymentintent_capture_mock.assert_called_once()
