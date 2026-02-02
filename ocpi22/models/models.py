from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.db import models
from rest_framework.exceptions import ValidationError


from ocpi22.util import ModelUtilMixin
import ocpi22.payments.models # noqa # For registering the payment model


class AuthorizationInfo(models.Model, ModelUtilMixin):
    # Status of the Token, and whether charging is allowed at the optionally given location.
    ALLOWED_CHOICES = (
        ("ALLOWED", "Allowed"),
        ("BLOCKED", "Blocked"),
        ("EXPIRED", "Expired token"),
        ("NO_CREDIT", "User has ho credit"),
        ("NOT_ALLOWED", "Not allowed"),
    )
    allowed = models.CharField(max_length=11, choices=ALLOWED_CHOICES)

    # The complete Token object for which this authorization was requested.
    token = models.ForeignKey("ocpi22.Token", on_delete=models.PROTECT)

    # Optional reference to the location if it was included in the request, and if the EV driver is allowed
    # to charge at that location. Only the EVSEs the EV driver is allowed to charge at are returned.
    # location = models.ForeignKey(Location, on_delete=models.PROTECT)

    # Reference to the authorization given by the eMSP, when given, this reference will be provided
    # in the relevant Session and/or CDR.
    authorization_reference = models.CharField(
        max_length=settings.OCPI_22_MAX_UID_LENGTH, blank=True, default=""
    )

    last_updated = models.DateTimeField(auto_now=True)


# Todo: OCPI tariff_id has to contain a valid OCHP tariffId (NLEVNT12345ABC)


class MultipleChoiceCharField(models.CharField):
    def __init__(self, *args, **kwargs):
        self.choices_enum = kwargs.pop("choices_enum", None)
        super().__init__(*args, **kwargs)

    @staticmethod
    def from_db_value(value, expression, connection):
        if value is None:
            return value
        return value.split(",")

    def to_python(self, value):
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return value.split(",")

    def get_prep_value(self, value):
        if isinstance(value, list):
            return ",".join(value)
        return value

    def validate(self, value, model_instance):
        if isinstance(value, list):
            for item in value:
                if item not in self.choices_enum.values:
                    raise ValidationError(_("%s is not a valid choice" % item))
        # super().validate(value, model_instance)


# Todo: CDR.id must contain the CPO-ID (NLEVN12345ABCDEFG...) [up to 36 characters total]
# Todo: CDR.id must follow the pattern: Regular Expression: [0-9A-Z]{1,36}
# Todo: Prevent creating EVSE linked to a Location owned by another party
