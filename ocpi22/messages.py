import markdown
from django.contrib import messages as django_messages
from django.utils.safestring import mark_safe
from rest_framework.renderers import BrowsableAPIRenderer


class Messages:
    @staticmethod
    def is_browsable(request) -> bool:
        return bool(
            request
            and hasattr(request, "accepted_renderer")
            and isinstance(request.accepted_renderer, BrowsableAPIRenderer)
        )

    def error(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.error(
                request, mark_safe(markdown.markdown(msg)), **kwargs
            )

    def warning(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.warning(
                request, mark_safe(markdown.markdown(msg)), **kwargs
            )

    def success(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.success(
                request, mark_safe(markdown.markdown(msg)), **kwargs
            )

    def info(self, request, msg, **kwargs):
        if self.is_browsable(request):
            return django_messages.info(
                request, mark_safe(markdown.markdown(msg)), **kwargs
            )


messages = Messages()
