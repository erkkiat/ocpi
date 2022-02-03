import datetime
from typing import Optional

import pytz
from icecream import ic
from nordpool import elspot
from pprint import pprint

# Initialize class for fetching Elspot prices
prices_spot = elspot.Prices()


# Initialize class for fetching Elsbas prices
# prices_bas = elbas.Prices()

def get_current_price(area) -> Optional[float]:
    """
    >>> type(get_current_price('FI'))
    <class 'float'>

    @param area:
    @return:
    """
    prices = prices_spot.hourly(areas=[area])
    current_price = [p for p in prices['areas'][0]['values'] if
                     p['start'] < datetime.datetime.now(pytz.utc) < p['end']]
    return current_price[0]['value'] / 1000 if len(current_price) else None
