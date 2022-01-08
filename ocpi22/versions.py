from rest_framework import routers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.reverse import reverse


def get_versions_dict(request):
    return [
        dict(
            version='2.2', url=request.build_absolute_uri(reverse('ocpi-22'))
        )
    ]


def get_endpoints_dict(request):
    R = "RECEIVER"
    S = "SENDER"

    return dict(
        version="2.2",
        endpoints=[
            dict(
                identifier="credentials",
                role=R,
                url=request.build_absolute_uri(reverse('credentials-list'))
            ),
            dict(
                identifier="credentials",
                role=S,
                url=request.build_absolute_uri(reverse('credentials-list'))
            ),
            dict(
                identifier="locations",
                role=S,
                url=request.build_absolute_uri(reverse('location-list'))
            ),
            # Todo: Locations receiver and Tokens sender are for simulator, and should only be active when in debug
            dict(
                identifier="locations",
                role=R,
                url=request.build_absolute_uri(reverse('location-list'))
            ),
            dict(
                identifier="tokens",
                role=R,
                url=request.build_absolute_uri(reverse('token-list'))
            ),
            dict(
                identifier="tokens",
                role=S,
                url=request.build_absolute_uri(reverse('token-list'))
            ),
            dict(
                identifier="tariffs",
                role=S,
                url=request.build_absolute_uri(reverse('tariff-list'))
            ),
            dict(
                identifier="tariffs",
                role=R,
                url=request.build_absolute_uri(reverse('tariff-list'))
            ),
            dict(
                identifier="sessions",
                role=S,
                url=request.build_absolute_uri(reverse('session-list'))
            ),
            dict(
                identifier="cdrs",
                role=S,
                url=request.build_absolute_uri(reverse('cdr-list'))
            ),
            dict(
                identifier="commands",
                role=R,
                url=request.build_absolute_uri(reverse('commands-list'))
            ),
        ]
    )


class OCPIBaseView(routers.APIRootView):
    """
    Welcome to the OCPI Connector Developer Central. You can start exploring the server by clicking the Versions link
    below.
    """

    # noinspection PyUnresolvedReferences
    def get(self, request, *args, **kwargs):
        """
        Compile the example URLs for the front page
        """

        result = dict(
            versions=request.build_absolute_uri(
                reverse('base-versions')
            ),
            openapi=request.build_absolute_uri(
                reverse('openapi-schema')
            ),
        )
        return Response(result)

    def get_view_name(self):
        return 'OCPI'


class BaseRouter(routers.DefaultRouter):
    APIRootView = OCPIBaseView


class VersionsViewSet(viewsets.ViewSet):
    publicly_visible = True  # This is understood by OCPIPermission

    @action(methods=['GET'], url_path='versions', detail=False)
    def versions(self, request, *_args, **_kwargs):
        return Response(get_versions_dict(request))
