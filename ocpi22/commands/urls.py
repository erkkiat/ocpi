from django.urls import path

from ocpi22.commands.commands import CommandsViewSet

urlpatterns = [
    path('commands/',
         CommandsViewSet.as_view({'get': 'list'}),
         name='commands-list'),
    path('commands/START_SESSION',
         CommandsViewSet.as_view({'get': 'start_session', 'post': 'start_session'}),
         name='commands-start-session'),
    path('commands/STOP_SESSION',
         CommandsViewSet.as_view({'get': 'stop_session', 'post': 'stop_session'}),
         name='commands-stop-session'),
    path('commands/RESERVE_NOW',
         CommandsViewSet.as_view({'get': 'reserve_now', 'post': 'reserve_now'}),
         name='commands-reserve-now'),
    path('commands/UNLOCK_CONNECTOR',
         CommandsViewSet.as_view({'get': 'unlock_connector', 'post': 'unlock_connector'}),
         name='commands-unlock-connector'),
    path('commands/hubresponse/<str:command_id>',
         CommandsViewSet.as_view({'post': 'hubresponse'}),
         name='commands-hubresponse'),
    path('commands/COMMAND_RESULT/<str:command>/<str:command_id>',
         CommandsViewSet.as_view({'get': 'command_result', 'post': 'command_result'}),
         name='commands-command-result'),
]
