class HoursTest:
    regular_hours = {'weekday': 1, 'period_begin': "08:00", 'period_end': "18:00"}

    exceptional_period = {'period_begin': '2021-01-01T08:00:00Z', 'period_end': '2021-01-01T10:00:00Z'}

    advanced_hours = {'regular_hours': [{'weekday': 1, 'period_begin': '08:00', 'period_end': '17:00'},
                                        {'weekday': 2, 'period_begin': '08:00', 'period_end': '17:00'},
                                        {'weekday': 3, 'period_begin': '08:00', 'period_end': '17:00'},
                                        {'weekday': 4, 'period_begin': '08:00', 'period_end': '17:00'},
                                        {'weekday': 6, 'period_begin': '10:00', 'period_end': '18:00'},
                                        {'weekday': 7, 'period_begin': '10:00', 'period_end': '18:00'}],
                      'twentyfourseven': False,
                      'exceptional_openings': [
                          {'period_begin': '2021-01-01T10:00:00Z', 'period_end': '2021-01-02T18:00:00Z'}],
                      'exceptional_closings': [
                          {'period_begin': '2021-01-03T10:00:00Z', 'period_end': '2021-01-04T18:00:00Z'}]}
