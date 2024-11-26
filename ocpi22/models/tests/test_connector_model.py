from ocpi22.tests.factories import ConnectorFactory


class TestConnectorModel:
    def test_energy_conversion_to_kilo_watts(self):
        connector = ConnectorFactory.build(
            uid="CONNECTOR_1",
            standard="IEC_62196_T2",
            format="",
            power_type="",
            max_voltage=-100,
            max_amperage=16,
            max_electric_power=14000,
            terms_and_conditions="https://www.berlin-supercharger.com/terms-and-conditions",
        )

        power_kw = connector.power_kw()

        assert power_kw == 14
