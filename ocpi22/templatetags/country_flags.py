from django import template

register = template.Library()


@register.filter(name='country_code')
def country_code(language) -> str:
    # Input language code is a string like 'en-us'
    # Output country code iso 2 is a string like 'gb'
    return dict(
        nn="no",
        nb="no",
        en="gb",
        da="dk",
        sq='al',
        uk='ua',
        el="gr",
        cs="cz",
    ).get(language, language)
