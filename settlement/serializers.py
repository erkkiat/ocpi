from rest_framework import serializers

from ocpi22.models.cdr import Cdr


class CsvCdrSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cdr
        exclude = ('tariffs', 'created', 'updated', 'credentials',)
