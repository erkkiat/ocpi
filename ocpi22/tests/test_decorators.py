import pytest
from dataclasses import dataclass

from ocpi22.choices import OcpiRolesEnum
from ocpi22.decorators import resolve_sender_identity
from ocpiconnector.party import Party


@dataclass
class FakeOcpiParty:
    role: OcpiRolesEnum
    country_code: str
    party_id: str


EMPTY_SENDER = Party("", "")
PTP_OCPI_PARTY = FakeOcpiParty(
    role=OcpiRolesEnum.PTP, country_code="NL", party_id="PAY"
)
EMSP_OCPI_PARTY = FakeOcpiParty(
    role=OcpiRolesEnum.EMSP, country_code="SE", party_id="EMS"
)


class TestResolveNonPtpSender:
    @pytest.mark.parametrize(
        "country_code, party_id, payload, sender_party, expected_cc, expected_pid",
        [
            ("FI", "CPO", {}, EMPTY_SENDER, "FI", "CPO"),
            (
                "",
                "",
                {"country_code": "DE", "party_id": "MSP"},
                EMPTY_SENDER,
                "DE",
                "MSP",
            ),
            ("", "", {}, Party("NL", "EMB"), "NL", "EMB"),
            (
                "FI",
                "CPO",
                {"country_code": "DE", "party_id": "MSP"},
                Party("NL", "EMB"),
                "FI",
                "CPO",
            ),
            ("", "", {}, EMPTY_SENDER, "", ""),
        ],
    )
    def test_resolve_sender_identity_non_ptp_resolves_in_correct_priority(
        self, country_code, party_id, payload, sender_party, expected_cc, expected_pid
    ):
        resolved_cc, resolved_pid = resolve_sender_identity(
            country_code=country_code,
            party_id=party_id,
            payload=payload,
            sender_party=sender_party,
            ocpi_party=None,
        )

        assert resolved_cc == expected_cc
        assert resolved_pid == expected_pid

    def test_resolve_sender_identity_non_ptp_ocpi_party_is_not_used_as_fallback(self):
        resolved_cc, resolved_pid = resolve_sender_identity(
            country_code="",
            party_id="",
            payload={},
            sender_party=EMPTY_SENDER,
            ocpi_party=EMSP_OCPI_PARTY,
        )

        assert resolved_cc == ""
        assert resolved_pid == ""


class TestResolvePtpSender:
    @pytest.mark.parametrize(
        "country_code, party_id, sender_party, expected_cc, expected_pid",
        [
            ("NL", "PAY", EMPTY_SENDER, "NL", "PAY"),
            ("", "", Party("NL", "PAY"), "NL", "PAY"),
            ("", "", EMPTY_SENDER, "NL", "PAY"),
            ("NL", "PAY", Party("DE", "OTH"), "NL", "PAY"),
        ],
    )
    def test_resolve_sender_identity_ptp_resolves_in_correct_priority(
        self, country_code, party_id, sender_party, expected_cc, expected_pid
    ):
        resolved_cc, resolved_pid = resolve_sender_identity(
            country_code=country_code,
            party_id=party_id,
            payload={},
            sender_party=sender_party,
            ocpi_party=PTP_OCPI_PARTY,
        )

        assert resolved_cc == expected_cc
        assert resolved_pid == expected_pid

    def test_resolve_sender_identity_ptp_returns_empty_when_all_sources_are_absent(
        self,
    ):
        empty_ptp = FakeOcpiParty(role=OcpiRolesEnum.PTP, country_code="", party_id="")

        resolved_cc, resolved_pid = resolve_sender_identity(
            country_code="",
            party_id="",
            payload={},
            sender_party=EMPTY_SENDER,
            ocpi_party=empty_ptp,
        )

        assert resolved_cc == ""
        assert resolved_pid == ""
