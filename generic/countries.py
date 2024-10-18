import pycountry
from django.utils.translation import gettext_noop as _

COUNTRIES_ISO_3 = [(c.alpha_3.upper(), _(c.name)) for c in pycountry.countries]
COUNTRIES_ISO_2 = [(c.alpha_2.upper(), _(c.name)) for c in pycountry.countries]
COUNTRIES_ISO_2_SET = {c.alpha_2.upper() for c in pycountry.countries}
COUNTRY_CHOICES = COUNTRIES_ISO_2
