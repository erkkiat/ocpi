from rest_framework.response import Response

from ocpi22.choices import MessageTexts


def get_message_by_language(messages: list, language: str) -> str:
    """
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), 'en')
    'Stopping charging session'
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), 'FI')
    'Latausistuntoa lopetellaan'
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), 'CH')
    'Stopping charging session'
    >>> get_message_by_language(MessageTexts.get('STOPPING_TO_CHARGE'), '')
    'Stopping charging session'
    """
    if not messages:
        return ''
    language = language.upper()
    for message in messages:
        if message.get('language') == language:
            return message.get('text')
    return get_message_by_language(messages, 'EN') if language != 'EN' else messages[0].get('text')


class ErrorLoggingResponse(Response):
    def __init__(self, data=None, status=None, template_name=None, headers=None, exception=False, content_type=None):
        if status >= 400:
            from ocpi22 import logging
            logging.error(f"Error {status}: {data}")
        super().__init__(data, status, template_name, headers, exception, content_type)
