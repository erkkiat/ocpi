from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from django.db.models import Sum, QuerySet
from rest_framework import viewsets, renderers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework_csv.renderers import CSVRenderer

from ocpi22.models.cdr import Cdr
from ocpi22.ocpi.serializers import CdrSerializer
from ocpi22.util import StandardResultsSetPagination
from settlement.serializers import CsvCdrSerializer


def get_date_range(params: dict) -> tuple[date, date]:
    def calculate_first_and_last_day(month, year):
        start_date = datetime(year, month, 1, 0, 0)
        end_date: datetime = start_date + relativedelta(months=1)
        end_date = datetime(end_date.year, end_date.month, 1, 0, 0) - relativedelta(
            seconds=1
        )
        return start_date, end_date

    month_ago = date.today() - relativedelta(months=1)
    month = int(params.get("month", month_ago.month))
    year = int(params.get("year", month_ago.year))
    return calculate_first_and_last_day(month, year)


class CdrReportViews(viewsets.GenericViewSet):
    # Todo: Limit access based on privileges set by admin

    model = Cdr
    queryset = Cdr.objects.all()
    lookup_field = "uid"
    serializer_class = CdrSerializer
    csv_serializer_class = CsvCdrSerializer
    pagination_class = StandardResultsSetPagination
    renderer_classes = (
        renderers.JSONRenderer,
        renderers.BrowsableAPIRenderer,
        CSVRenderer,
    )

    def get_cdrs_in_date_range(self, request) -> QuerySet:
        queryset = Cdr.objects.all()
        date_range = get_date_range(request.GET)
        if not date_range:
            raise ValidationError("A range of dates is needed for the billing report")
        queryset = queryset.filter(
            start_date_time__range=date_range
        )  # This is inclusive
        self.start_date, self.end_date = date_range
        return queryset

    @action(methods=["GET"], detail=False)
    def summary(self, request) -> Response:
        """
        This is the monthly summary of charge sessions per CPO.

        ## Query parameters
        * `month` - the month to summarize, e.g. "5"
        * `year` - the year to summarize, e.g. "2022"

        For example, /api/cpo/v2/reports/billing/summary/?month=5&year=2022.
        To output in CSV format, append URL with "?format=csv".
        """
        result = (
            self.get_cdrs_in_date_range(request)
            .values("billed_to")
            .order_by("billed_to")
        )
        paginator = self.pagination_class()
        result = result.annotate(Sum("total_cost_excl_vat")).annotate(
            Sum("total_energy")
        )

        if request.GET.get("format", "").lower() == "csv":
            return Response(list(result))  # Not paginated on purpose
        result = paginator.paginate_queryset(result, request)
        return paginator.get_paginated_response(
            data=dict(start_date=self.start_date, end_date=self.end_date, data=result)
        )

    @action(
        methods=["GET"],
        detail=False,
        url_name="list",
        name="Charging session list",
        url_path="list",
    )
    def session_list(self, request) -> Response:
        """
        This is the full list of charging sessions filtered with the query parameters below.

        ## Query parameters
        * `date_from` - inclusive start datetime, if time is not specified, 0:00:00 is assumed
        * `date_to` - exclusive end datetime, if time is not specified, 0:00:00 is assumed
        * `limit` - the paging limit, i.e. the maximum amount of results returned
        * `offset` - the page returned, if all entries were not already shown

        You can limit the date range of the entries returned. For example,
        /api/cpo/v2/reports/billing/list/?date_from=2022-06-01&date_to=2022-07-01.
        Since date_from is inclusive and date_to is exclusive, so this would give you the transactions with
        last_updated in June. If you don't specify the time, it is assumed 0:00:00.

        If the list is longer than 100 entries, it will be paged.
        You can force paging using "limit" and "offset" query parameters,
        for example, /api/cpo/v2/reports/billing/list/?limit=10&offset=2. This query would return a maximum of
        10 results starting from entry 11.

        You can select the output format between JSON and CSV by using
        the "Accept" header or the "format" query parameter,
        for example /api/cpo/v2/reports/billing/list/?format=csv.

        __Curl example__:
        _curl -H "Accept: application/json; indent=4" "http://yourhostname/api/cpo/v2/reports/billing/list/" --user yourusername_
        """
        result = self.queryset
        # result = self.get_cdrs_in_date_range(request)

        paginator = self.pagination_class()
        if request.GET.get("format", "").lower() == "csv":
            serializer = self.csv_serializer_class(instance=result, many=True)
            return Response(serializer.data)
        result = paginator.paginate_queryset(result, request)
        serializer = self.serializer_class(instance=result, many=True)
        return paginator.get_paginated_response(serializer.data)
