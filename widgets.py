from django import forms
from django.contrib.admin.widgets import AdminURLFieldWidget
from django.core.validators import URLValidator
from django.db import models


class BootstrapTextInputWidget(forms.TextInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={"class": "form-control", **(attrs or {})})


class BootstrapURLFieldWidget(AdminURLFieldWidget):
    def __init__(self, attrs=None, validator_class=URLValidator):
        super().__init__(attrs={"class": "form-control", **(attrs or {})})
        self.validator = validator_class()


class BootstrapIntegerFieldWidget(forms.NumberInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={"class": "form-control", **(attrs or {})})


formfield_overrides = {
    models.CharField: {"widget": BootstrapTextInputWidget},
    models.URLField: {"widget": BootstrapURLFieldWidget},
    models.IntegerField: {"widget": BootstrapIntegerFieldWidget},
    models.PositiveIntegerField: {"widget": BootstrapIntegerFieldWidget},
    models.PositiveSmallIntegerField: {"widget": BootstrapIntegerFieldWidget},
    models.SmallIntegerField: {"widget": BootstrapIntegerFieldWidget},
    models.BigIntegerField: {"widget": BootstrapIntegerFieldWidget},
}
