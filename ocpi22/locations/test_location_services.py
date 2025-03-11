import pytest

from ocpi22.locations.services import LocationService
from ocpi22.models.location import Location
from ocpi22.tests.factories import LocationFactory, CredentialsFactory


class TestLocationServices:
    @pytest.mark.django_db
    def test_get_allowed_locations_queryset_returns_everything_when_no_credentials_provided(
        self,
    ):
        tampere = LocationFactory(uid="TAMPERE")
        joensu = LocationFactory(uid="JOENSU")
        queryset = Location.objects.all()
        filtered_queryset = LocationService.get_allowed_locations_queryset(
            None, queryset
        )
        assert list(filtered_queryset) == [tampere, joensu]

    @pytest.mark.django_db
    def test_get_allowed_locations_queryset_returns_allowed_locations_only(self):
        helsinki = LocationFactory(uid="HELSINKI-ALLOWED")
        espoo = LocationFactory(uid="ESPOO-ALLOWED")
        LocationFactory(uid="VANTAA-NOT-ALLOWED")

        all_locations = Location.objects.all()
        credentials = CredentialsFactory(
            allowed_locations=["HELSINKI-ALLOWED", "ESPOO-ALLOWED"]
        )
        filtered_queryset = LocationService.get_allowed_locations_queryset(
            credentials, all_locations
        )

        assert list(filtered_queryset) == [helsinki, espoo]

    @pytest.mark.django_db
    def test_get_allowed_locations_queryset_returns_all_locations_when_allowed_locations_is_empty_list(
        self,
    ):
        Location.objects.all().delete()
        LocationFactory(uid="KUOPIO")
        LocationFactory(uid="OULU")

        all_locations = Location.objects.all()
        credentials = CredentialsFactory(allowed_locations=[])
        filtered_queryset = LocationService.get_allowed_locations_queryset(
            credentials, all_locations
        )
        assert filtered_queryset == all_locations
