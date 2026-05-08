from dataclasses import dataclass, field

import generic.countries


def party_from_str(party_str: str) -> "Party":
    return Party(*party_str.split("*"))


@dataclass(eq=True, frozen=True)
class Party:
    country_code: str = field(default="")
    party_id: str = field(default="")

    def __post_init__(self):
        if (
            self.country_code
            and self.country_code.upper() not in generic.countries.COUNTRIES_ISO_2_SET
        ):
            raise ValueError(
                f"Country code {self.country_code} is not a valid ISO 3166-1 alpha-2 code"
            )

    def __str__(self):
        return f"{self.country_code}*{self.party_id}"

    def __bool__(self):
        return bool(self.country_code and self.party_id)

    def get_role_if_exists(self):
        from ocpi22.models.credentials import CredentialsRole

        return CredentialsRole.get_if_exists(
            country_code__iexact=self.country_code, party_id__iexact=self.party_id
        )

    @classmethod
    def from_str(cls, party_str):
        return cls(*party_str.split("*"))
