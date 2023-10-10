import cachetools
from cachetools.func import ttl_cache
from django.db.models.signals import pre_save
from django.dispatch import receiver

from ocpi22 import choices
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Connector

issues_cache = dict()


@cachetools.cached(cache=issues_cache)
def get_connector_issues():
    connectors_with_overlapping_tariffs = Connector.objects.filter(tariff_ids__isnull=False).distinct()
    tariffs_overlap_list = []
    for connector in connectors_with_overlapping_tariffs:
        if connector.tariff_ids.count() > 1:
            tariffs_overlap_list.append(connector)

    results = [
        dict(
            heading='Connectors without a Tariff',
            help_text='When a Tariff is not specified, it is not possible to calculate price and to create an invoice. '
                      'Please use the below links to access the corresponding EVSE and <b>select a Tariff, '
                      'then save the connector</b>.',
            items=Connector.objects.filter(tariff_ids=None)
        ),
        dict(
            heading='Connectors with overlapping Tariffs',
            help_text='When Tariffs overlap, it also prevents from calculating price and creating an invoice. '
                      'Please use the below links to access the corresponding EVSE and <b>select only one Tariff, '
                      'then save the connector</b>.',
            items=tariffs_overlap_list
        )
    ]

    return results


@ttl_cache(ttl=5 * 60)
def get_credential_issues():
    results = [
        dict(
            heading='Parties Offline',
            help_text='These are parties with active Credentials, but who are unreachable. '
                      'You can remove this warning by <b>editing the Credentials and '
                      'changing the connection status to "suspended"</b>, '
                      'or by contacting the party and asking them to fix the situation. '
                      '<p><i>This warning updates every 5 minutes, '
                      'so the connection may have been restored already</i>.</p>',
            items=Credentials.objects.filter(connection_status=choices.OFFLINE)
        ),
    ]

    return results


@ttl_cache(ttl=5 * 60)
def get_issues() -> list:
    return get_credential_issues() + get_connector_issues()


# Todo: Sessions active for over 1 day
# Todo: Sessions with 0 kWh? Not good to warn about them since you can't do anything. Maybe a report is needed?
# Todo: Sessions or CDRs with mixed currencies or not matching Tariff currency
# Todo: Connectors with mixed currency Tariffs (not needed yet, since just a single Tariff per connector)
# Todo: Any other issues with CDRs
# Todo: Analyse which elements overlap in two Tariffs (in the future)


def issue_count(issue_list) -> int:
    return sum([
        len(i.get('items')) for i in issue_list
    ])


@receiver(pre_save)
def object_pre_save(sender, instance, raw, **_kwargs):
    if raw:
        return
    # Issues will be recompiled whenever an object changes, in case the issue has been resolved
    get_issues.cache_clear()
    if sender == Connector:
        get_connector_issues.cache_clear()
    if sender == Credentials:
        get_credential_issues.cache_clear()
