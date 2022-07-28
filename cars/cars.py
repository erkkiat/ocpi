import os
from dataclasses import dataclass, field

import requests
from cachetools.func import ttl_cache
from django.utils.functional import cached_property

from cars.test_data import cars_json


@dataclass(eq=True, frozen=True)
class ElectricCar:
    battery: str
    energy: str
    consumption: str
    range: int
    dc_charger: str
    dc_charger_power: int
    ac_charger: str
    ac_charger_power: int
    brand: str
    model: str
    variant: str
    original_json: str
    connectors: list = field(default_factory=[])

    @cached_property
    def full_name(self):
        return self.__str__()

    @cached_property
    def name(self):
        return self.full_name.lower()

    @cached_property
    def search_name(self):
        return remove_spacers(self.name)  # Cache also the name for search() efficiency

    @cached_property
    def id(self):
        return replace_spacers(self.name, '-')

    def __str__(self):
        return f'{self.brand} {self.model} {self.variant}'.strip()

    def __repr__(self):
        return self.__str__()


def replace_spacers(s: str, replacement='') -> str:
    return s.replace(' ', replacement).replace('-', replacement).replace('_', replacement)


def remove_spacers(s: str) -> str:
    return replace_spacers(s, '')


def get_json(url):
    return requests.get(url, timeout=10).json()


@ttl_cache(maxsize=1, ttl=86400)  # 24 hours cache
def get_models() -> dict:
    results = dict()
    if os.environ.get('TEST'):
        cars = cars_json
    else:
        cars = get_json('https://raw.githubusercontent.com/chargeprice/open-ev-data/master/data/ev-data.json')
    for car in cars['data']:
        energy = car.get('energy_consumption', {})
        consumption = energy.get('average_consumption', 0)
        battery = car.get('usable_battery_size', 0)
        dc_charger = car.get('dc_charger', {})
        ac_charger = car.get('ac_charger', {})
        car.pop('id', None)
        car.pop('brand_id', None)

        result = ElectricCar(
            battery=battery,
            energy=energy,
            consumption=consumption,
            range=int(battery / (consumption + 0.001) * 100),
            dc_charger=dc_charger,
            dc_charger_power=int(dc_charger.get('max_power', 0)) if dc_charger else 0,
            ac_charger=ac_charger,
            ac_charger_power=int(ac_charger.get('max_power', 0)) if ac_charger else 0,
            brand=car.get('brand', ''),
            model=car.get('model', ''),
            variant=car.get('variant', ''),
            connectors=[],
            original_json=car,
        )

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

        results[result.id] = result
    return results


def search(substr: str) -> list:
    substr = remove_spacers(substr.lower())
    return [value for key, value in get_models().items() if substr in value.search_name]


@ttl_cache(maxsize=100, ttl=3600)  # 1 hour cache
def model_exists(id: str) -> bool:
    models = get_models()
    return id in models
