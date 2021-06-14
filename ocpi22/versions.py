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
                url=request.build_absolute_uri(reverse('credentials-credentials'))
            ),
            dict(
                identifier="credentials",
                role=S,
                url=request.build_absolute_uri(reverse('credentials-credentials'))
            ),
            # dict(
            #     identifier="locations",
            #     role=S,
            #     url=reverse('locations')
            # ),
            # dict(
            #     identifier="tokens",
            #     role=R,
            #     url=reverse('tokens')
            # ),
            # dict(
            #     identifier="credentials",
            #     role=R,
            #     url=reverse('credentials')
            # ),
            # dict(
            #     identifier="credentials",
            #     role=R,
            #     url=reverse('credentials')
            # ),
        ]
    )


class OCPIBaseView(routers.APIRootView):
    """
    This is a test.
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
