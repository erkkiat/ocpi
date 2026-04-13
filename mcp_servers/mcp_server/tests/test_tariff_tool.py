import pytest
from django.core.exceptions import ObjectDoesNotExist

from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.tariff import SolidTariff, Tariff, TariffElement, PriceComponent
from ocpi22.models.business_details import BusinessDetails
from mcp_servers.mcp_server.tools import (
    get_tariff_details,
    format_tariff_as_markdown,
)


@pytest.mark.django_db
class TestTariffTool:
    """Test tariff tool functionality"""

    @pytest.fixture
    def setup_data(self):
        """Create test data for tariff tests"""
        # Create business details
        operator_bd = BusinessDetails.objects.create(name="Operator CPO")
        msp_bd = BusinessDetails.objects.create(name="MSP EMSP")
        ocpi_bd = BusinessDetails.objects.create(name="OCPI Master")

        # Create credentials roles
        operator = CredentialsRole.objects.create(
            country_code="FI",
            party_id="CPO",
            role="CPO",
            business_details=operator_bd,
        )
        msp = CredentialsRole.objects.create(
            country_code="FI",
            party_id="MSP",
            role="EMSP",
            business_details=msp_bd,
        )
        ocpi_master = CredentialsRole.objects.create(
            country_code="FI",
            party_id="OC1",
            role="CPO",
            business_details=ocpi_bd,
        )

        # Create OCPI Tariff
        tariff = Tariff.objects.create(
            uid="TARIFF001",
            currency="EUR",
            ocpi_master=ocpi_master,
            type="REGULAR",
        )

        # Create tariff element with price component
        tariff_element = TariffElement.objects.create(tariff=tariff)
        PriceComponent.objects.create(
            tariff_element=tariff_element,
            type="ENERGY",
            price=0.25,
            vat=25.0,
            step_size=1000,
        )

        # Create SolidTariff
        solid_tariff = SolidTariff.objects.create(
            external_id="SOLID001",
            currency="EUR",
            price_per_kwh=0.25,
            operator=operator,
            msp=msp,
            ocpi_tariff=tariff,
        )

        return {"solid_tariff": solid_tariff, "tariff": tariff}

    def test_get_tariff_by_solid_tariff_id(self, setup_data):
        """Test retrieving tariff by SolidTariff external_id"""
        solid_tariff = setup_data["solid_tariff"]

        result = get_tariff_details(id=solid_tariff.external_id)

        assert result is not None
        assert f"**External ID:** `{solid_tariff.external_id}`" in result
        assert "SolidTariff (Master Data from CPMS)" in result

    def test_get_tariff_by_ocpi_tariff_uid(self, setup_data):
        """Test retrieving tariff by OCPI Tariff uid"""
        tariff = setup_data["tariff"]

        result = get_tariff_details(id=tariff.uid)

        assert result is not None
        assert "SolidTariff (Master Data from CPMS)" in result
        assert "Corresponding OCPI Tariff" in result

    def test_get_tariff_missing_id(self):
        """Test that ValueError is raised when id is not provided"""
        with pytest.raises(ValueError, match="ID parameter is required"):
            get_tariff_details(id="")

    def test_get_tariff_empty_id(self):
        """Test that ValueError is raised when id is empty string"""
        with pytest.raises(ValueError, match="ID parameter is required"):
            get_tariff_details(id="")

    def test_get_tariff_not_found(self):
        """Test that ObjectDoesNotExist is raised when tariff not found"""
        with pytest.raises(ObjectDoesNotExist, match="Tariff not found"):
            get_tariff_details(id="NONEXISTENT")

    def test_format_tariff_as_markdown(self, setup_data):
        """Test that tariff is formatted as markdown correctly"""
        solid_tariff = setup_data["solid_tariff"]

        result = format_tariff_as_markdown(solid_tariff)

        # Check for key sections
        assert "# Tariff Information" in result
        assert "## SolidTariff (Master Data from CPMS)" in result
        assert "## Corresponding OCPI Tariff" in result

        # Check for specific values
        assert solid_tariff.external_id in result
        assert solid_tariff.currency in result

    def test_format_tariff_without_ocpi_tariff(self):
        """Test formatting SolidTariff without OCPI tariff"""
        # Create business details
        operator_bd = BusinessDetails.objects.create(name="Operator CPO")
        msp_bd = BusinessDetails.objects.create(name="MSP EMSP")

        operator = CredentialsRole.objects.create(
            country_code="FI",
            party_id="CPO",
            role="CPO",
            business_details=operator_bd,
        )
        msp = CredentialsRole.objects.create(
            country_code="FI",
            party_id="MSP",
            role="EMSP",
            business_details=msp_bd,
        )

        # Create SolidTariff without OCPI tariff
        solid_tariff = SolidTariff.objects.create(
            external_id="SOLID002",
            currency="EUR",
            price_per_kwh=0.30,
            operator=operator,
            msp=msp,
            ocpi_tariff=None,
        )

        result = format_tariff_as_markdown(solid_tariff)

        # Should still work without OCPI tariff
        assert "# Tariff Information" in result
        assert "SolidTariff (Master Data from CPMS)" in result
        assert solid_tariff.external_id in result

    def test_format_tariff_with_tariff_elements(self, setup_data):
        """Test that tariff elements are included in markdown"""
        solid_tariff = setup_data["solid_tariff"]

        result = format_tariff_as_markdown(solid_tariff)

        assert "## Tariff Elements" in result

    def test_select_related_optimization(self, setup_data):
        """Test that select_related is used for efficient queries"""
        solid_tariff = setup_data["solid_tariff"]

        # This should not trigger N+1 queries
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as queries:
            result = get_tariff_details(id=solid_tariff.external_id)
            assert result is not None
            # Should be around 2-3 queries, allowing some flexibility
            assert len(queries) <= 5, f"Expected at most 5 queries, got {len(queries)}"

    def test_ocpi_tariff_without_solid_tariff(self, setup_data):
        """Test that error is raised when OCPI tariff exists but no SolidTariff references it"""
        tariff = setup_data["tariff"]
        # Create a new OCPI tariff that's not referenced by any SolidTariff
        new_tariff = Tariff.objects.create(
            uid="TARIFF002",
            currency="EUR",
            ocpi_master=tariff.ocpi_master,
            type="REGULAR",
        )

        with pytest.raises(
            ObjectDoesNotExist, match="is not referenced by any SolidTariff"
        ):
            get_tariff_details(id=new_tariff.uid)
