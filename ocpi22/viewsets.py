import re

from django.utils.safestring import mark_safe
from rest_framework import viewsets

from util import replace_links


class FlowchartViewSet(viewsets.GenericViewSet):
    flowchart = None
    message = (
        "%% It seems that the Mermaid javascript plugin is not active, so the flow diagram is not visible. "
        "Please contact us to get this fixed.<br/><br/>\n"
    )

    def get_view_description(self, html=False) -> str:
        result = super().get_view_description(html)
        if self.flowchart:
            result = super().get_view_description(html)
            result = result.replace("{{flowchart}}", self.get_flowchart())
        return mark_safe(replace_links(result))

    def get_flowchart(self):
        def color(active: bool) -> str:
            return (
                "fill:#6e6,stroke:#282,stroke-width:2px;\n"
                if active
                else "fill:#eee,stroke:#888,stroke-width:2px;\n"
            )

        def remove_numbers(step: str) -> str:
            return re.sub(r"\d", "", step)

        def link(step, url):
            """Create a Mermaid link"""
            return f'click {step} "{url}";\n'

        action = getattr(self, "action", None)
        steps = (f"{step[0]}({step[1]});\n" for step in self.flowchart["steps"])
        colors = (
            f"style {step[0]} {color(action == remove_numbers(step[0]))}"
            for step in self.flowchart["steps"]
        )
        links = (
            link(step[0], step[2]) for step in self.flowchart["steps"] if len(step) > 2
        )
        result = (
            f'<div class="mermaid" style="min-width: 800px">\n{self.message}\n\nflowchart LR;'
            "\nlinkStyle default stroke-width:3px;\n"
            f"{''.join(steps)}\n{self.flowchart['process']}\n"
            f"{''.join(colors)}\n{''.join(links)}</div>"
        )
        return result
