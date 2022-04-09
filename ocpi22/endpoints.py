# from ocpi22.models.credentials import Endpoint


# def find_endpoints(identifier=None, role=None, endpoints=Endpoint.objects.all()):
#     """
#     >>> endpoints = [dict(identifier='AA*BBB', role='CPO'), dict(identifier='CC*DDD', role='EMSP')]
#     >>> find_endpoints('AA*BBB', 'CPO', endpoints=endpoints)
#     {'identifier': 'AA*BBB', 'role': 'CPO'}
#     >>> find_endpoints(role='EMSP', endpoints=endpoints)
#     {'identifier': 'CC*DDD', 'role': 'EMSP'}
#
#     @param identifier:
#     @param role:
#     @param endpoints:
#     @return:
#     """
#     if identifier:
#         identifier = identifier.lower()
#     if role:
#         role = role.lower()
#
#     for endpoint in endpoints:
#         ep_identifier = endpoint.get('identifier').lower()
#         ep_role = endpoint.get('role').lower()
#         if (not identifier or ep_identifier == identifier) and ep_role == role:
#             return endpoint
