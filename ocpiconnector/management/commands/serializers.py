from rest_framework import serializers


class VersionSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=10)
    url = serializers.URLField()


class VersionsSerializer(serializers.Serializer):
    data = VersionSerializer(many=True)
