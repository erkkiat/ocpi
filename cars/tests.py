from unittest import TestCase

from icecream import ic

from cars.cars import get_models, search


class TestCars(TestCase):
    def testCars(self):
        get_models()
        get_models()
        self.assertEqual(get_models.cache_info().hits, 1, 'cars.get_models() seems not to be cached')
        self.assertEqual(len(search('model   s')), 22, 'Unexpected number of results with "model s" in them')
        self.assertEqual(len(search('range')), 11, 'Unexpected number of results with "range" in them')
        # ic(search('range'))
