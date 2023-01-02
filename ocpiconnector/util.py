import calendar
import datetime
import time
from collections import OrderedDict
from functools import lru_cache
from gettext import gettext
from itertools import chain
from typing import Any, Union

from django.contrib.messages.storage.session import SessionStorage
from django.db.models import TimeField


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


def recursive_sort_dict(d: dict) -> dict:
    def _sorted_subdict(d: Any) -> Union[dict, list[dict]]:
        if isinstance(d, dict):
            return recursive_sort_dict(d)
        return d

    result = dict()
    if isinstance(d, (list, tuple)):
        return [_sorted_subdict(i) for i in d]
    for item in d.items():
        # print(f'Item: {item}')
        result[item[0]] = _sorted_subdict(item[1])
    return dict(sorted(result.items(), key=lambda x: x[0]))


def consecutive_ranges(numbers):
    """
    Written by OpenAI ChatGPT
    >>> consecutive_ranges([1,2,3,6,7,8,10])
    [[1, 3], [6, 8], [10, 10]]
    """
    # Initialize empty list to hold the resulting sublists
    ranges = []

    # Initialize variables to keep track of the current range
    start = None
    end = None

    # Iterate over the numbers in the input list
    for number in numbers:
        # If the current range is not set, set it to the current number
        if start is None:
            start = number
            end = number
        # If the current number is one more than the current range end, extend the range
        elif number == end + 1:
            end = number
        # If the current number is not part of the current range, add the range to the result and start a new range
        else:
            ranges.append([start, end])
            start = number
            end = number

    # Add the final range to the result
    ranges.append([start, end])

    return ranges


@lru_cache
def weekday_range_to_str(weekday_list: tuple[int]) -> str:
    """
    >>> weekday_range_to_str((0,1,3,2,4,5,6))
    ''
    >>> weekday_range_to_str((0,1,3,2,4))
    'Weekdays'
    >>> weekday_range_to_str((0,1,5,6))
    'Mon-Tue, weekends'
    >>> weekday_range_to_str(tuple())
    ''
    >>> weekday_range_to_str((5,6))
    'Weekends'
    >>> weekday_range_to_str((0,1,3,4,6))
    'Mon-Tue, Thu-Fri, Sun'
    """
    if not weekday_list:
        return ''
    weekdays = list(calendar.day_abbr)
    results = []
    ranges = consecutive_ranges(sorted(weekday_list))

    for start, stop in ranges:
        if start == stop:
            results.append(gettext(weekdays[start]))
        elif start == 5 and stop == 6:
            results.append(gettext('weekends'))
        elif start == 0 and stop == 4:
            results.append(gettext('weekdays'))
        elif start == 0 and stop == 6:
            pass
        else:
            results.append(f'{gettext(weekdays[start])}-{gettext(weekdays[stop])}')

    if not results:
        return ''

    result = ', '.join(results)
    # Capitalize the first letter, leave the rest alone
    return f'{result[0].upper()}{result[1:]}'


def humanize_time(t: Union[datetime.time, TimeField]) -> str:
    if not t.minute:
        return str(t.hour)
    return f'{t.hour}:{t.minute:02d}'


class DedupMessageMixin(object):
    def add(self, level, message, extra_tags):
        messages = chain(self._loaded_messages, self._queued_messages)
        for m in messages:
            if m.message == message:
                return
        return super(DedupMessageMixin, self).add(level, message, extra_tags)


class SessionDedupStorage(DedupMessageMixin, SessionStorage):
    pass
