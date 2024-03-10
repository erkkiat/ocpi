import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


@dataclass
class DateRange:
    start: date
    end: date


def calculate_monday(d: date) -> date:
    """
    Calculate the Monday of the week of the given date.

    >>> calculate_monday(date(2022, 5, 5))
    datetime.date(2022, 5, 2)
    >>> calculate_monday(date(2024, 3, 3))
    datetime.date(2024, 2, 26)
    >>> calculate_monday(date(2024, 3, 4))
    datetime.date(2024, 3, 4)

    @param d: the date
    @return: date of the Monday of the week of the given date
    """
    return d - timedelta(days=d.weekday())


def calculate_invoicing_periods(start_date: date, end_date: date, period_length_weeks: int) -> Iterable[DateRange]:
    """
    Calculate the invoicing periods between the given start and end dates.
    If the period length is 4 weeks, the periods will be calendar months instead of weeks.
    Includes at least one full week or month around both dates.

    >>> list(calculate_invoicing_periods(date(2024, 3, 3), date(2024, 3, 3), 1))
    [DateRange(start=datetime.date(2024, 2, 26), end=datetime.date(2024, 3, 3))]
    >>> list(calculate_invoicing_periods(date(2024, 3, 3), date(2024, 3, 3), 4))
    [DateRange(start=datetime.date(2024, 3, 1), end=datetime.date(2024, 3, 31))]
    >>> list(calculate_invoicing_periods(date(2024, 3, 3), date(2024, 4, 20), 4))
    [DateRange(start=datetime.date(2024, 3, 1), end=datetime.date(2024, 3, 31)), DateRange(start=datetime.date(2024, 4, 1), end=datetime.date(2024, 4, 30))]
    >>> list(calculate_invoicing_periods(date(2024, 3, 3), date(2024, 3, 4), 1))
    [DateRange(start=datetime.date(2024, 2, 26), end=datetime.date(2024, 3, 3)), DateRange(start=datetime.date(2024, 3, 4), end=datetime.date(2024, 3, 10))]
    """
    if start_date > end_date:
        raise ValueError('Start date must be before end date')
    if period_length_weeks <= 0:
        raise ValueError('Period length must be positive')
    if period_length_weeks > 4:
        raise ValueError('Period length must be less than a month')
    if period_length_weeks < 4:
        start_date = calculate_monday(start_date)
    while start_date <= end_date:
        if period_length_weeks == 4:
            # A one-month invoicing period is an exception, then we will use months instead of weeks
            date_range = get_first_and_last_date_for_month(start_date)
            yield date_range
            start_date = date_range.end + timedelta(days=1)
        else:
            # The period length is less than a month
            period_end = start_date + timedelta(days=7*period_length_weeks-1)
            yield DateRange(start_date, period_end)
            start_date = period_end + timedelta(days=1)


def get_first_and_last_date_for_month(d: date) -> DateRange:
    """
    Calculate the dates for the month which the given date belongs to.

    >>> get_first_and_last_date_for_month(date(2024, 3, 3))
    DateRange(start=datetime.date(2024, 3, 1), end=datetime.date(2024, 3, 31))
    >>> get_first_and_last_date_for_month(date(2024, 12, 1))
    DateRange(start=datetime.date(2024, 12, 1), end=datetime.date(2024, 12, 31))
    >>> get_first_and_last_date_for_month(date(2024, 2, 29))
    DateRange(start=datetime.date(2024, 2, 1), end=datetime.date(2024, 2, 29))
    """
    year = d.year
    month = d.month
    first_day = date(year, month, 1)
    last_day_of_month = calendar.monthrange(year, month)[1]  # Get the number of days in the month
    last_day = date(year, month, last_day_of_month)
    return DateRange(first_day, last_day)
