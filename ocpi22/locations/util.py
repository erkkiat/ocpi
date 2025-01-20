from typing import Optional

from ocpi22.models.business_details import BusinessDetails
from ocpi22.models.image import OCPIImage


def get_or_create_business_details(*_args, **kwargs) -> Optional[BusinessDetails]:
    """
    Find a BusinessDetails object and create it based on name and optional website.
    No duplicates are allowed to be created.

    >>> before = BusinessDetails.objects.all().count()
    >>> get_or_create_business_details(name='Test', website='http://test.com')
    <BusinessDetails: Test>
    >>> get_or_create_business_details(name='Test', website='http://test.com')
    <BusinessDetails: Test>
    >>> after = BusinessDetails.objects.all().count()
    >>> after - before
    1

    @param _args:
    @param kwargs:
    @return:
    """
    if not kwargs:
        return None

    image = None
    logo = kwargs.pop("logo", None)
    if logo and isinstance(logo, dict):
        image, _created = OCPIImage.objects.get_or_create(
            url=logo.pop("url", ""),
            thumbnail=logo.pop("thumbnail", ""),
            category=logo.pop("category", ""),
            image_type=logo.pop("type", ""),
            defaults=logo,
        )
    business_details, _created = BusinessDetails.objects.get_or_create(
        **kwargs, defaults=dict(logo=image)
    )
    return business_details
