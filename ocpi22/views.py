from django.shortcuts import render

from ocpiconnector.ocpi_identities import ocpi_platform


def home(request):
    context = dict(
        ocpi_platform=ocpi_platform
    )
    return render(request, template_name='index.html', context=context)
