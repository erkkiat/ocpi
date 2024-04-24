from typing import Optional

from ocpi22.models.business_details import BusinessDetails


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

    logo = kwargs.pop('logo', '')
    business_details, _created = BusinessDetails.objects.get_or_create(**kwargs, defaults=dict(logo=logo))
    return business_details
