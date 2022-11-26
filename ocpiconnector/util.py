import time
from collections import OrderedDict
from typing import Any


class Timer:
    interval = 0.0

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.end = time.time()
        self.interval = self.end - self.start

    def __float__(self):
        return self.interval

    def __repr__(self):
        return str(self.interval)

    def __bool__(self):
        return bool(self.interval)


def _sorted_subdict(d: Any) -> OrderedDict:
    # print(f'subdict candidate: {d}')
    if isinstance(d, dict):
        return recursive_sort_dict(d)
    return d


def recursive_sort_dict(d: dict) -> OrderedDict:
    result = dict()
    for item in d.items():
        # print(f'Item: {item}')
        result[item[0]] = _sorted_subdict(item[1])
    return OrderedDict(sorted(result.items(), key=lambda x: x[0]))
