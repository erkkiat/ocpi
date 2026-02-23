from ocpi22.credentials.versions import get_endpoints_dict


def _payments_endpoints(version="2.2.1") -> list:
    result = get_endpoints_dict(version=version)
    return [e for e in result["endpoints"] if e["identifier"] == "payments"]


class TestGetEndpointsDictPaymentsEntry:
    def test_get_endpoints_dict_includes_payments_receiver_and_sender_for_cpo(self):
        payments = _payments_endpoints()
        roles = {e["role"] for e in payments}

        assert roles == {"RECEIVER", "SENDER"}

    def test_get_endpoints_dict_payments_receiver_url_points_to_payments_root(self):
        payments = _payments_endpoints()
        receiver = next(e for e in payments if e["role"] == "RECEIVER")

        assert receiver["url"].endswith("/payments/")

    def test_get_endpoints_dict_payments_sender_url_points_to_payments_root(self):
        payments = _payments_endpoints()
        sender = next(e for e in payments if e["role"] == "SENDER")

        assert sender["url"].endswith("/payments/")

    def test_get_endpoints_dict_payments_urls_do_not_contain_terminals(self):
        payments = _payments_endpoints()

        assert all("terminals" not in e["url"] for e in payments)

    def test_get_endpoints_dict_payments_urls_do_not_contain_financial_advice(self):
        payments = _payments_endpoints()

        assert all("financial-advice-confirmations" not in e["url"] for e in payments)
