import pytest
from django.forms.models import model_to_dict
from rest_framework.exceptions import ValidationError

from ocpi22.models.credentials import validate_allowed_locations, Credentials
from ocpi22.tests.factories import CredentialsFactory


class TestCredentialsModel:
    @pytest.mark.parametrize("allowed_locations", [[], ["SOME-ID"]])
    def test_allowed_locations_validator_does_not_throw_on_valid_data(
        self, allowed_locations
    ):
        validate_allowed_locations(allowed_locations)

    @pytest.mark.parametrize(
        "allowed_locations", [1, "must-be-list", {"wrong-type": "cannot be dict"}]
    )
    def test_allowed_location_validator_raises_when_incorrect_type_data_is_provided(
        self, allowed_locations
    ):
        with pytest.raises(ValidationError, match="This field must be a list"):
            validate_allowed_locations(allowed_locations)

    @pytest.mark.parametrize("allowed_locations", [[], ["valid-uid"]])
    def test_credentials_model_saves_allowed_locations(self, db, allowed_locations):
        credential = CredentialsFactory(allowed_locations=allowed_locations)
        assert credential.allowed_locations == allowed_locations

    @pytest.mark.parametrize(
        "allowed_locations", [1, "must-be-list", {"wrong-type-again": "cannot be dict"}]
    )
    def test_credentials_model_throws_when_incorrect_data_types_provided(
        self, db, allowed_locations
    ):
        with pytest.raises(ValidationError, match="This field must be a list"):
            credential_data = CredentialsFactory.build(
                allowed_locations=allowed_locations
            )
            credential_data = model_to_dict(credential_data)
            Credentials.objects.create(**credential_data)
        assert not Credentials.objects.filter(allowed_locations=allowed_locations)
