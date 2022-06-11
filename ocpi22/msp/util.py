from ocpi22.choices import MessageTexts


def get_message_by_language(messages: list, language: str) -> str:
    """
    >>> get_message_by_language(MessageTexts.STOPPING_TO_CHARGE, 'EN')
    'Stopping charging session'
    >>> get_message_by_language(MessageTexts.STOPPING_TO_CHARGE, 'FI')
    'Latausta lopetellaan'
    >>> get_message_by_language(MessageTexts.STOPPING_TO_CHARGE, 'ES')
    'Stopping charging session'
    >>> get_message_by_language(MessageTexts.STOPPING_TO_CHARGE, '')
    'Stopping charging session'
    """
    if not messages:
        return ''
    language = language.upper()
    for message in messages:
        if message.get('language') == language:
            return message.get('text')
    return get_message_by_language(messages, 'EN') or messages[0].get('text')
