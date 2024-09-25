from rest_framework import serializers
from .models import Webhook


class WebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webhook
        fields = ["detail_url", "url"]

    detail_url = serializers.SerializerMethodField(read_only=True)

    def get_detail_url(self, obj):
        return obj.get_admin_url()
