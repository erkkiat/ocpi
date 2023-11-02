import json
import pickle
from dataclasses import dataclass
from unittest.mock import patch

from django.test import TestCase

from ocpiconnector.testutil import compare_lists_recursively
from util import RedisStore


@dataclass
class TestDataClass:
    a: int
    b: int


class TestRedisStore(TestCase):
    def setUp(self):
        self.store = RedisStore(namespace='test_namespace', expiration=60)

    def test_storing(self):

        with patch('util.redis_store') as mock_set:
            # Store a string
            self.store['test'] = 'value'
            method_calls = list(map(lambda x: x.args, mock_set.method_calls))
            self.assertTrue(compare_lists_recursively(
                method_calls, [('test_namespace:test', pickle.dumps('value'), 60)]
            ))

            # Store a dataclass
            mock_set.reset_mock()
            dataclass_data = TestDataClass(1, 2)
            self.store['dataclass'] = dataclass_data
            method_calls = list(map(lambda x: x.args, mock_set.method_calls))
            self.assertTrue(compare_lists_recursively(
                method_calls, [('test_namespace:dataclass', pickle.dumps(dataclass_data), 60)]
            ))

        # Store a dict actually to Redis
        dict_data = {'a': 1, 'b': 2}
        self.store['test'] = dict_data
        self.assertTrue(pickle.loads(pickle.dumps(dict_data)))
        # self.assertEqual(pickle.loads(self.store.retrieve('test_namespace:test')), dict_data)
        c = self.store['test']
        self.assertEqual(self.store['test'], dict_data)

        # Store a dataclass actually to Redis
        self.store['dataclass'] = dataclass_data
        self.assertEqual(self.store['dataclass'], dataclass_data)  # Should have the same content as the dict

    def test_retrieving(self):
        with patch('util.redis_store.get') as mock_get:
            mock_get.return_value = pickle.dumps(dict(a=1, b=2))
            _dummy = self.store['test']
            self.assertEqual(mock_get.call_args.args, ('test_namespace:test',))

            # Get an item which doesn't exist
            mock_get.return_value = None
            with self.assertRaises(KeyError):
                _a = self.store['test2']
            self.assertEqual(mock_get.call_args.args, ('test_namespace:test2',))

            # Retrieve a dict
            dict_data = '{"a": 1, "b": 2}'
            mock_get.return_value = dict_data
            self.assertEqual(self.store['test'], json.loads(dict_data))

            # Retrieve a broken dict
            broken_data = '{"a": 1, "b": 2'
            mock_get.return_value = broken_data
            with self.assertRaises(KeyError):
                self.assertEqual(self.store['test'], broken_data)
