from rest_framework import serializers

from ocpi22 import choices
from ocpi22.models.displaytext import DisplayText
from ocpi22.util import LanguageChoiceField


class DisplayTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = DisplayText
        fields = ["language", "text"]

    language = LanguageChoiceField(required=False, choices=choices.LANGUAGE_CHOICES)
