import pytest
from django.test import RequestFactory
from django.http import HttpResponse
from django.conf import settings
from middlewares import AllowHealthCheckMiddleware


@pytest.mark.django_db
def test_health_check_middleware_success(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)

    request = RequestFactory().get("/health-check/")
    request.META["HTTP_HOST"] = "testserver"

    middleware = AllowHealthCheckMiddleware(lambda req: HttpResponse("Fallback"))
    response = middleware(request)

    assert response.status_code == 200
    assert response.content == b"OK"


@pytest.mark.django_db
def test_health_check_middleware_failure(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)

    request = RequestFactory().get("/health-check/")
    request.META["HTTP_HOST"] = "testserver"

    monkeypatch.setattr(AllowHealthCheckMiddleware, "check_health", lambda self: False)
    middleware = AllowHealthCheckMiddleware(lambda req: HttpResponse("Fallback"))
    response = middleware(request)

    assert response.status_code == 500
    assert response.content == b"Service Unhealthy"
