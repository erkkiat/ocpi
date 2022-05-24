import requests
from cachetools.func import ttl_cache
from icecream import ic


class ElectricCar:
    def __str__(self):
        return f'{self.brand} {self.model} {self.variant}'.strip()

    def __repr__(self):
        return self.__str__()


def replace_spacers(s: str, replacement='') -> str:
    return s.replace(' ', replacement).replace('-', replacement).replace('_', replacement)


def remove_spacers(s: str) -> str:
    return replace_spacers(s, '')


@ttl_cache(maxsize=1, ttl=86400)  # 24 hours cache
def get_models() -> dict:
    results = dict()
    response = requests.get('https://raw.githubusercontent.com/chargeprice/open-ev-data/master/data/ev-data.json')
    cars = response.json()
    for car in cars['data']:
        result = ElectricCar()
        result.battery = car.get('usable_battery_size', '')
        result.energy = car.get('energy_consumption')
        result.consumption = result.energy.get('average_consumption') if result.energy else '0'

        result.range = int(result.battery / result.consumption * 100)

        result.dc_charger = car.get('dc_charger')
        result.dc_charger_power = int(result.dc_charger.get('max_power', '0')) if result.dc_charger else 0

        result.ac_charger = car.get('ac_charger')
        result.ac_charger_power = result.ac_charger.get('max_power', '0') if result.ac_charger else '0'

        result.brand = car.get('brand', '')
        result.model = car.get('model', '')
        result.variant = car.get('variant', '')

        result.connectors = []
        connector_choices = {
            'ccs': 'CC',
            'chademo': 'CD',
            'type2': 'TB',
            'type1': 'T1',
            'tesla_ccs': 'CC',
            'tesla_suc': 'TS',
        }
        if isinstance(result.dc_charger, dict):
            for c in result.dc_charger.get('ports'):
                result.connectors.append(connector_choices[c])
        if isinstance(result.ac_charger, dict):
            for c in result.ac_charger.get('ports'):
                result.connectors.append(connector_choices[c])

        name = str(result).lower()
        result.search_name = remove_spacers(name)  # Cache also the name for search() efficiency
        result.id = replace_spacers(name, '-')
        results[result.id] = result
    return results


def search(substr: str) -> list:
    substr = remove_spacers(substr.lower())
    return [(key, str(value)) for key, value in get_models().items() if substr in value.search_name]
