from rest_framework import serializers


class DisplayTextSerializer(serializers.Serializer):
    # Language Code ISO 639-1.
    language = serializers.CharField(max_length=2)

    # Text to be displayed to a end user. No markup, html etc. allowed.
    text = serializers.CharField(max_length=512)
