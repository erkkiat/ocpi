import json
import pickle
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from django.test import TestCase

from util import RedisStore


@dataclass
class TestDataClass:
    a: int
    b: int


class TestRedisStore(TestCase):
    def setUp(self):
        self.store = RedisStore(namespace="test_namespace", expiration=60)

    def test_storing(self):
        with patch("util.redis_store") as mock_set:
            # Store a string
            self.store["test"] = "value"
            method_calls = list(map(lambda x: x.args, mock_set.method_calls))
            assert method_calls == [("test_namespace:test", pickle.dumps("value"), 60)]

            # Store a dataclass
            mock_set.reset_mock()
            dataclass_data = TestDataClass(1, 2)
            self.store["dataclass"] = dataclass_data
            method_calls = list(map(lambda x: x.args, mock_set.method_calls))
            assert method_calls == [
                ("test_namespace:dataclass", pickle.dumps(dataclass_data), 60)
            ]

        # Store a dict actually to Redis
        dict_data = {"a": 1, "b": 2}
        self.store["test"] = dict_data
        assert pickle.loads(pickle.dumps(dict_data))
        assert self.store["test"] == dict_data

        # Store a dataclass actually to Redis
        self.store["dataclass"] = dataclass_data
        assert self.store["dataclass"] == dataclass_data

    def test_retrieving(self):
        with patch("util.redis_store.get") as mock_get:
            mock_get.return_value = pickle.dumps(dict(a=1, b=2))
            _dummy = self.store["test"]
            assert mock_get.call_args.args == ("test_namespace:test",)

            # Get an item which doesn't exist
            mock_get.return_value = None
            with self.assertRaises(KeyError):
                _a = self.store["test2"]
            assert mock_get.call_args.args == ("test_namespace:test2",)

            # Retrieve a dict
            data = '{"a": 1, "b": 2}'
            mock_get.return_value = data
            assert self.store["test"] == json.loads(data)

            # Retrieve a broken dict
            broken_data = '{"a": 1, "b": 2'
            mock_get.return_value = broken_data

            with pytest.raises(KeyError):
                assert self.store["test"] == broken_data
