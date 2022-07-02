import doctest


def load_tests(_loader, tests, _ignore):
    tests.addTests(doctest.DocTestSuite('ocpi22.cpo.util'))
    return tests
