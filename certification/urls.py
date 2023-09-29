from django.urls import path

from certification.views import certification_home

urlpatterns = [
    path('', certification_home, name='certification-status')
]
