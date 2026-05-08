import pytest

from ocpi22.credentials.versions import get_endpoints_dict


def _endpoints_by_module(version="2.2.1") -> dict:
    result = get_endpoints_dict(version=version)
    return {e["identifier"]: e for e in result["endpoints"]}


@pytest.mark.django_db
class TestGetEndpointsDictPaymentsEntry:
    def test_get_endpoints_dict_includes_payments_module_for_cpo(self):
        endpoints = _endpoints_by_module()

        assert "payments" in endpoints

    def test_get_endpoints_dict_payments_module_has_receiver_role(self):
        endpoints = _endpoints_by_module()

        assert endpoints["payments"]["role"] == "RECEIVER"

    def test_get_endpoints_dict_payments_module_url_points_to_payments_root(self):
        endpoints = _endpoints_by_module()

        assert endpoints["payments"]["url"].endswith("/payments/")

    def test_get_endpoints_dict_payments_module_url_does_not_contain_terminals(self):
        endpoints = _endpoints_by_module()

        assert "terminals" not in endpoints["payments"]["url"]

    def test_get_endpoints_dict_payments_module_url_does_not_contain_financial_advice(
        self,
    ):
        endpoints = _endpoints_by_module()

        assert "financial-advice-confirmations" not in endpoints["payments"]["url"]
