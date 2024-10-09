import pytest


def capital_case(x):
    return x.capitalize()


def test_capital_case():
    assert capital_case("semaphore") == "Semaphore", "Should be 'Semaphore'"


def test_raises_exception_on_non_string_arguments():
    with pytest.raises(AttributeError):
        capital_case(9)
