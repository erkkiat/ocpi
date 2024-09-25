from unittest import TestCase

from webhooks.views import callback_serializers


def load_tests(_loader, tests, _ignore):
    # tests.addTests(doctest.DocTestSuite('webhooks.views'))
    return tests


class TestWebhooks(TestCase):
    def test_outbound_serializers(self):
        # Make sure each callback has an OutboundSerializer and a ResponseSerializer
        list(
            map(
                lambda x: (x.OutboundSerializer, x.ResponseSerializer),
                callback_serializers.values(),
            )
        )
