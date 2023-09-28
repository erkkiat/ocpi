from django.shortcuts import render
from django.utils import timezone

from certification.decorators import certification_step_list
from ocpi22.choices import CERTIFICATION_TOPIC_DICT, CERTIFICATION_TOPIC_CHOICES
from ocpiconnector import settings


def certification_disabled(request, template_name='certification/disabled.html'):
    """Show the certification disabled page to the user"""

    return render(request, template_name)


def certification_home(request, template_name='certification/home.html'):
    """Show the certification progress to the user"""

    if not settings.CERTIFICATION_MODE:
        return certification_disabled(request)

    def get_data(topic):
        steps = certification_step_list[topic]
        for step in steps:
            step.retrieve()
        # map(lambda x: x.retrieve(), steps)  <-- this doesn't work
        return dict(heading=CERTIFICATION_TOPIC_DICT[topic], steps=steps)

    items = [get_data(x[0]) for x in CERTIFICATION_TOPIC_CHOICES]

    return render(
        request,
        template_name,
        context=dict(
            certification_items=items,
            date_now=timezone.now()
        )
    )
