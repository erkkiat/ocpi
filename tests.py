from dataclasses import dataclass
from unittest.mock import patch

from django.test import TestCase
from icecream import ic

from util import RedisStore


class TestRedisStore(TestCase):
    def setUp(self):
        self.store = RedisStore(namespace='test_namespace', expiration=60)

    def test_storing(self):
        @dataclass
        class TestDataClass:
            a: int
            b: int

        dataclass_data = TestDataClass(1, 2)

        with patch('redis.Redis.set') as mock_set:
            # Store a string
            self.store['test'] = 'value'
            self.assertEqual(mock_set.call_args.args, ('test_namespace-test', 'value', 60))

            # Store a dataclass
            self.store['dataclass'] = dataclass_data
            self.assertEqual(mock_set.call_args.args, ('test_namespace-dataclass', '{"a": 1, "b": 2}', 60))

        # Store a dict actually to Redis
        dict_data = {'a': 1, 'b': 2}
        self.store['test'] = dict_data
        self.assertEqual(self.store['test'], dict_data)

        # Store a dataclass actually to Redis
        self.store['dataclass'] = dataclass_data
        self.assertEqual(self.store['dataclass'], dict_data)  # Should have the same content as the dict

    def test_retrieving(self):
        with patch('redis.Redis.get') as mock_get:
            _a = self.store['test']
            self.assertEqual(mock_get.call_args.args, ('test_namespace-test',))

            # Get an item which doesn't exist
            mock_get.return_value = None
            with self.assertRaises(KeyError):
                _a = self.store['test2']
            self.assertEqual(mock_get.call_args.args, ('test_namespace-test2',))

            # Retrieve a broken dict
            broken_data = '{"a": 1, "b": 2'
            mock_get.return_value = broken_data
            self.assertEqual(self.store['test'], broken_data)
