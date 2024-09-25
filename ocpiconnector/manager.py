from cachetools import TTLCache, cached
from django.db import models
from rest_framework.exceptions import ValidationError


class PartnerQuerySet(models.QuerySet):
    """When running as HUB, limit the visibility of roaming partners
    to the ones that have an agreement with the current party"""

    def partner_filter(self, request):
        from ocpiconnector.ocpi_identities import ocpi_platform
        from ocpi22.models.credentials import CredentialsRole

        assert hasattr(
            self.model, "ocpi_master"
        ), f"The model {self.model} must have an ocpi_master field in order to use partner_filter()"
        if ocpi_platform.is_hub and hasattr(request, "credentials"):
            from ocpi22.ocpi.partners import get_partners

            agreed_parties = get_partners(request)
            if self.model is CredentialsRole:
                return self.filter(pk__in=agreed_parties)
            return self.filter(ocpi_master__in=agreed_parties)
        return self

    def get_if_exists(
        self,
        *args,
        raise_exception=False,
        multiple_is_ok_just_get_the_first_one=False,
        **kwargs,
    ) -> any:
        """
        Like Manager.get() but doesn't raise an exception if the object doesn't exist.
        If there are more than one object with the given criteria, raises an exception.
        If multiple_is_ok_just_get_the_first_one is True, returns the first object found.
        If raise_exception is True, raises an exception if the object doesn't exist. Otherwise, returns None.

        @param args: Any positional arguments for Manager.filter()
        @param raise_exception: Raise an exception if the object doesn't exist or if there are more than one
        and multiple_is_ok_just_get_the_first_one is False
        @param multiple_is_ok_just_get_the_first_one: In the case of multiple objects, just return the first one
        @param kwargs: Keyword arguments for Manager.filter(), the criteria to filter the objects with
        @return: The first object found or None
        """
        # ic(args, kwargs)
        queryset = self.filter(*args, **kwargs)

        if multiple_is_ok_just_get_the_first_one:
            return queryset.first()

        count = queryset.count()

        if count == 1:
            return queryset.first()

        if count > 1:
            raise ValidationError(
                f"There are more than one {self.model.__name__} with the criteria {kwargs} "
                "in the database"
            )

        if raise_exception:
            error_message = (
                f"{self.model.__name__} with UID "
                f"{kwargs.get('uid', 'N/A')} doesn't exist in the database"
            )
            raise self.model.DoesNotExist(error_message)

        return None


parther_manager_cache = TTLCache(maxsize=100, ttl=300)


class PartnerManager(models.Manager):
    """
    This is a custom manager used by the OCPI objects
    """

    def get_queryset(self):
        return PartnerQuerySet(self.model, using=self._db)

    def partner_filter(self, request):
        return self.get_queryset().partner_filter(request)

    def get_if_exists(self, *args, **kwargs):
        return self.get_queryset().get_if_exists(*args, **kwargs)

    @cached(cache=parther_manager_cache)
    def get_cached(self, *args, **kwargs):
        return self.get(*args, **kwargs)
