# from nordpool import elspot

# Initialize class for fetching Elspot prices
# prices_spot = elspot.Prices()

## TODO: This was not working because of commented elspot so commenting it out for now


# Initialize class for fetching Elsbas prices
# prices_bas = elbas.Prices()

# def get_current_price(area) -> Optional[float]:
#     """
#     The Nordpool API seems to malfunction or deny our queries
#     # >>> type(get_current_price('FI'))
#     <class 'float'>
#
#     @param area:
#     @return:
#     """
#     prices = prices_spot.hourly(areas=[area])
#     current_price = [p for p in prices['areas'][0]['values'] if
#                      p['start'] < datetime.datetime.now(pytz.utc) < p['end']]
#     return current_price[0]['value'] / 1000 if len(current_price) else None
