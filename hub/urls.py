from django.urls import path

from hub import views

urlpatterns = [
    path(
        "role/<int:role1>/agreement/<int:role2>/remove/",
        views.remove_roaming_agreement,
        name="remove-roaming-agreement",
    ),
    path(
        "role/<int:role>/agreement/add/",
        views.list_roaming_parties,
        name="list-roaming-parties",
    ),
    path(
        "role/<int:role1>/agreement/<int:role2>/add/",
        views.add_roaming_agreement,
        name="add-roaming-agreement",
    ),
]
