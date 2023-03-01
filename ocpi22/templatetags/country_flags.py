from django import template

register = template.Library()


@register.filter(name='country_code')
def country_code(language) -> str:
    # Input language code is a string like 'en'
    # Output country code iso 2 is a string like 'gb'
    return {'nn': "no", 'nb': "no", 'en': "gb", 'da': "dk", 'sq': 'al', 'uk': 'ua', 'el': "gr", 'cs': "cz", 'sv': "se",
            'et': "ee", 'sl': "si", 'ca': "es", 'gl': "es", 'cy': "gb-wls", 'ga': "ie", 'sr': "rs",
            'vi': "vn", 'zh': "cn", 'ja': "jp", 'ko': "kr", 'ar': "sa",
            'he': "il", 'ur': "pk", 'fa': "ir", 'ps': "af", 'sd': "pk", 'ku': "iq", 'yi': "de",
            'ms': "my", 'sw': "tz", 'am': "et", 'km': "kh", 'lo': "la", 'my': "mm", 'bn': "bd", 'pa': "in", 'gu': "in",
            'ta': "in", 'te': "in", 'kn': "in", 'ml': "in", 'si': "lk", 'th': "th", 'hy': "am",
            'eu': "es", 'be': "by", 'bs': "ba"}.get(language, language)
