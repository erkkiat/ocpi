from django.urls import path

from settlement.views import CdrReportViews

urlpatterns = [
    path(
        "cdr/",
        CdrReportViews.as_view({"get": "session_list"}),
        name="cdr-list",
    ),
]
