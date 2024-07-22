from django.urls import path
from .views import WebhookListCreate, WebhookDetail

urlpatterns = [
    path('', WebhookListCreate.as_view(), name='webhook-list-create'),
    path('<str:event>/', WebhookDetail.as_view(), name='webhook-detail'),
]
