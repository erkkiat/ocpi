import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from ocpi22.models.token import Token
from ocpi22.ocpi.util import OCPIPaginationAndHeaders


@pytest.mark.django_db
def test_that_pagination_returns_correct_items_and_headers():
    items = list(range(1, 21))
    factory = APIRequestFactory()
    request = factory.get("/?limit=5&offset=10")
    drf_request = Request(request)

    paginator = OCPIPaginationAndHeaders()
    paginated_items = paginator.paginate_queryset(items, drf_request)

    assert paginated_items == [11, 12, 13, 14, 15]
    response = paginator.get_paginated_response(paginated_items)
    assert response.status_code == 200
    assert response.headers == {
        "Content-Type": "text/html; charset=utf-8",
        "X-Total-Count": "20",
        "X-Limit": "50",
        "Link": '<http://testserver/?limit=5&offset=15>; rel="next"',
    }


@pytest.mark.django_db
def test_that_pagination_returns_correct_headers_when_date_range_is_in_the_future():
    items = Token.objects.all()
    factory = APIRequestFactory()
    request = factory.get("/?date_from=3000-01-01")
    drf_request = Request(request)

    paginator = OCPIPaginationAndHeaders()
    paginated_items = paginator.paginate_queryset(items, drf_request)
    assert paginated_items is not None

    response = paginator.get_paginated_response(paginated_items)
    assert response.status_code == 200
    assert response.headers == {
        "Content-Type": "text/html; charset=utf-8",
        "X-Total-Count": "0",
        "X-Limit": "50",
    }
