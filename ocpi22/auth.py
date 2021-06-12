from icecream import ic
from rest_framework import exceptions
from rest_framework.permissions import DjangoModelPermissions


def check_auth_token(token):
    ic(token)
    return token == 'eki' or token == "IpbJOXxkxOAuKR92z0nEcmVF3Qw09VG7I7d/WCg0koM="


class OCPIPermission(DjangoModelPermissions):
    """
    Check for valid OCPI authentication header and secondarily basic auth with local user IDs
    """

    def has_permission(self, request, view):
        # Get the OCPI Authorization header or if none, the auth-test query param
        # Remove the "Token" keyword if present to get just the token value
        auth_id = request.META.get('HTTP_AUTHORIZATION',
                                   request.GET.get('auth-test', '')).replace('Token ', '')
        # Check for token authentication, secondarily basic auth
        if check_auth_token(auth_id) or super().has_permission(request, view):
            return True
        raise exceptions.PermissionDenied
