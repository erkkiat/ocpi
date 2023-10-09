from django.urls import path

from certification import views
from ocpiconnector import settings

urlpatterns = [
    path('', views.certification_home, name='certification-status')
]

if settings.CERTIFICATION_MODE:
    urlpatterns += [
        path('session/', views.sessions, name='certification-sessions'),
        path('session/start/', views.start_session, name='certification-start-session'),
        path('session/stop/', views.stop_session, name='certification-stop-session'),
    ]
