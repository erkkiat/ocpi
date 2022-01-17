from ocpi22.models.credentials import Endpoint


def find_endpoints(identifier, role, endpoints=Endpoint.objects.all()):
    for endpoint in endpoints:
        ep_identifier = endpoint.get('identifier').lower()
        ep_role = endpoint.get('role').lower()
        if ep_identifier == identifier and ep_role == role:
            return endpoint
