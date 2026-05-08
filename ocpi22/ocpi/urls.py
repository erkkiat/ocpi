from django.urls import path, include

from ocpi22.ocpi.api import CdrViewSet, TokenViewSet, TariffViewSet, SessionViewSet

urlpatterns = [
    # CDRs
    path("cdrs/", CdrViewSet.as_view({"get": "list", "post": "post"}), name="cdr-list"),
    path(
        "cdrs/<str:country_code>/<str:party_id>/<str:uid>",
        CdrViewSet.as_view({"get": "get"}),
        name="cdr-by-id",
    ),
    # Tokens
    path(
        "tokens/<str:token_uid>/authorize",
        TokenViewSet.as_view({"post": "authorize"}),
        name="token-authorize",
    ),
    path(
        "tokens/",
        TokenViewSet.as_view({"get": "list", "put": "put"}),
        name="token-list",
    ),
    path(
        "tokens/<str:country_code>/<str:party_id>/<str:uid>",
        TokenViewSet.as_view({"get": "get", "put": "put", "patch": "patch"}),
        name="token-by-id",
    ),
    # Tariffs
    path(
        "tariffs/",
        TariffViewSet.as_view({"get": "list", "put": "put"}),
        name="tariff-list",
    ),
    path(
        "tariffs/<str:country_code>/<str:party_id>/<str:uid>",
        TariffViewSet.as_view({"get": "get", "put": "put", "delete": "delete"}),
        name="tariff-by-id",
    ),
    # Sessions
    path(
        "sessions/",
        SessionViewSet.as_view({"get": "list", "put": "put", "patch": "patch"}),
        name="session-list",
    ),
    path(
        "sessions/<str:country_code>/<str:party_id>/<str:uid>",
        SessionViewSet.as_view({"get": "get", "put": "put", "patch": "patch"}),
        name="session-by-id",
    ),
    # Payments (EVRF DirectPayment Module)
    path("payments/", include("ocpi22.payments.urls")),
]
