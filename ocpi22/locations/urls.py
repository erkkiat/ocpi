from django.urls import path

from ocpi22.locations.location import LocationViewSet, EvseViewSet

urlpatterns = [
    path('',
         LocationViewSet.as_view({'get': 'list'}),
         name='location-list'),
    path('<str:country_code>/<str:party_id>/<str:uid>',
         LocationViewSet.as_view({'get': 'get', 'put': 'put', 'patch': 'patch'}),
         name='location-by-id'),
    path('<str:country_code>/<str:party_id>/<str:uid>/<str:evse_uid>',
         EvseViewSet.as_view({'get': 'get', 'put': 'put', 'patch': 'patch'}),
         name='location-by-evse-id'),
]