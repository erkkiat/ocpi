from django.contrib import messages as django_messages
from rest_framework.renderers import BrowsableAPIRenderer

default_error_messages = dict(
    object_missing='There is no {name} with UID `{uid}` in our database'
)


class Messages:
    @staticmethod
    def is_browsable(request):
        return isinstance(request.accepted_renderer, BrowsableAPIRenderer)

    def error(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.error(request, msg, **kwargs)

    def warning(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.warning(request, msg, **kwargs)

    def success(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.success(request, msg, **kwargs)

    def info(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.info(request, msg, **kwargs)


messages = Messages()
