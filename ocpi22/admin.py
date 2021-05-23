from django.contrib import admin

from ocpi22.models import Token


class TokenAdmin(admin.ModelAdmin):
    model = Token


admin.site.register(Token, TokenAdmin)
