from ocpi22.cpo.repositories import SolidTariffRepository


class SolidTariffService:
    solid_tariff_repository = SolidTariffRepository()

    def get_all_latest_solid_tariffs(self):
        return self.solid_tariff_repository.get_latest_with_unique_external_id_and_msp()
