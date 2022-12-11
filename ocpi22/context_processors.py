import os

import cachetools

from ocpi22.issues import issue_count, get_issues
from ocpiconnector.ocpi_identities import ocpi_identities


@cachetools.cached(cache={})
def _get_environment():
    return dict(
        header_color=os.environ.get('HEADER_COLOR'),
        roles=" / ".join([f'{key}: {value}' for key, value in ocpi_identities.items()]),
    )


def export_environment_variables(_request):
    return _get_environment()


def export_issue_count(_request):
    return dict(
        issue_count=issue_count(get_issues())
    )
