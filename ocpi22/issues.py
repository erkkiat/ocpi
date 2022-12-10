import cachetools
from django.db.models.signals import pre_save
from django.dispatch import receiver

from ocpi22.models.location import Connector

issues_cache = dict()


@cachetools.cached(cache=issues_cache)
def get_issues() -> list:
    connectors_with_overlapping_tariffs = Connector.objects.filter(tariff_ids__isnull=False).distinct()
    tariffs_overlap_list = []
    for connector in connectors_with_overlapping_tariffs:
        if connector.tariff_ids.count() > 1:
            tariffs_overlap_list.append(connector)

    results = [
        dict(
            heading='Connectors without a Tariff',
            help_text='When a Tariff is not specified, it is not possible to calculate price and to create an invoice. '
                      'Please use the below links to access the corresponding EVSE and select a Tariff, '
                      'then save the connector.',
            items=Connector.objects.filter(tariff_ids=None)
        ),
        dict(
            heading='Connectors with overlapping Tariffs',
            help_text='When Tariffs overlap, it also prevents from calculating price and creating an invoice. '
                      'Please use the below links to access the corresponding EVSE and select only one Tariff, '
                      'then save the connector.',
            items=tariffs_overlap_list
        )
    ]

    return results


def issue_count(issue_list) -> int:
    return sum([
        len(i.get('items')) for i in issue_list
    ])


@receiver(pre_save, sender=Connector)
def account_pre_save(sender, instance: Connector, **_kwargs):
    # Issues will be recompiled whenever a Connector changes
    get_issues.cache_clear()
