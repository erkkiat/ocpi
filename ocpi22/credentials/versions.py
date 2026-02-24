from django.conf import settings
from rest_framework import routers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ocpi22.ocpi.util import OCPIResponse
from ocpi22.util import build_absolute_uri
from util import reverse
from ocpiconnector.ocpi_identities import ocpi_platform


def get_versions_url_221():
    return build_absolute_uri(settings.OCPI_221_URL)


def get_versions_url_22():
    return build_absolute_uri(settings.OCPI_22_URL)


def get_versions_dict():
    # Called often by hubinfo, make sure no excess steps
    # Cannot use caching due to changing requests

    return [
        {"version": "2.2", "url": get_versions_url_22()},
        {"version": "2.2.1", "url": get_versions_url_221()},
    ]


def get_endpoints_dict(request=None, version=None) -> dict:
    R = "RECEIVER"
    S = "SENDER"

    assert request or version, "Either request or version must be given"
    if not version:
        version = request.version

    result = dict(
        version=version,
        endpoints=[
            dict(
                identifier="credentials",
                role=R,
                url=build_absolute_uri(reverse("credentials-list", args=[version])),
            ),
            # Todo: Gireve will not accept us as a Credentials receiver, if there will be others requiring it,
            #  figure out how to do it
            dict(
                identifier="hubclientinfo",
                role=R,
                url=build_absolute_uri(reverse("clientinfo-list", args=[version])),
            ),
        ],
    )

    if ocpi_platform.is_hub:
        result["endpoints"] += [
            dict(
                identifier="hubclientinfo",
                role=S,
                url=build_absolute_uri(reverse("clientinfo-list", args=[version])),
            ),
        ]

    if ocpi_platform.is_cpo or ocpi_platform.is_hub:
        result["endpoints"] += [
            dict(
                identifier="locations",
                role=S,
                url=build_absolute_uri(reverse("location-list", args=[version])),
            ),
            dict(
                identifier="commands",
                role=R,
                url=build_absolute_uri(reverse("commands-list", args=[version])),
            ),
            dict(
                identifier="payments",
                role=R,
                url=build_absolute_uri(reverse("payments-list", args=[version])),
            ),
            dict(
                identifier="tariffs",
                role=S,
                url=build_absolute_uri(reverse("tariff-list", args=[version])),
            ),
            dict(
                identifier="sessions",
                role=S,
                url=build_absolute_uri(reverse("session-list", args=[version])),
            ),
            dict(
                identifier="cdrs",
                role=S,
                url=build_absolute_uri(reverse("cdr-list", args=[version])),
            ),
            dict(
                identifier="tokens",
                role=R,
                url=build_absolute_uri(reverse("token-list", args=[version])),
            ),
        ]
    if ocpi_platform.is_emsp or ocpi_platform.is_hub:
        result["endpoints"] += [
            # This is for authorize Token
            dict(
                identifier="locations",
                role=R,
                url=build_absolute_uri(reverse("location-list", args=[version])),
            ),
            dict(
                identifier="cdrs",
                role=R,
                url=build_absolute_uri(reverse("cdr-list", args=[version])),
            ),
            dict(
                identifier="tokens",
                role=S,
                url=build_absolute_uri(reverse("token-list", args=[version])),
            ),
            dict(
                identifier="tariffs",
                role=R,
                url=build_absolute_uri(reverse("tariff-list", args=[version])),
            ),
            dict(
                identifier="sessions",
                role=R,
                url=build_absolute_uri(reverse("session-list", args=[version])),
            ),
        ]
    return result


class OCPIBaseView(routers.APIRootView):
    """
    This is the OCPI root. You can start exploring the hierarchy by clicking the link
    below.
    """

    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the front page
        """

        result = dict(
            versions=request.build_absolute_uri(
                reverse("base-versions", request=request)
            ),
        )
        return Response(result)

    def get_view_name(self):
        return "OCPI"


class BaseRouter(routers.DefaultRouter):
    APIRootView = OCPIBaseView


class VersionsViewSet(viewsets.ViewSet):
    publicly_visible = True  # This is understood by OCPIPermission

    @action(methods=["GET"], url_path="versions", detail=False)
    def versions(self, request, *_args, **_kwargs):
        """
        This is the OCPI "versions" endpoint. A requesting party will use this information
        for choosing the OCPI version used between us and them.
        """
        return OCPIResponse(get_versions_dict())
