from unittest import TestCase
from unittest.mock import patch, Mock

from cars.cars import get_models, search
from cars import test_data


class TestCars(TestCase):
    @patch('cars.cars.get_json', return_value=test_data.cars_json)
    def testCars(self, _get_json_mock: Mock):
        get_models.cache_clear()
        get_models()
        # This is a cache test basically, since it's our implementation we use
        self.assertEqual(get_models.cache_info().hits, 0,
                         'cars.get_models() seems to use the cache too early or cache is not cleared')
        self.assertEqual(get_models.cache_info().misses, 1, 'cars.get_models() seems not to be cached')
        get_models()
        self.assertEqual(get_models.cache_info().hits, 1, 'cars.get_models() seems not to be cached')
        self.assertEqual(len(search('artega   karo')), 1, 'Unexpected number of results with "Artega Karo" in them')
