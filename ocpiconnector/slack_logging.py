import logging
import os

from slack_logger import SlackHandler, SlackFormatter


class MyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if 'autoreload' in record.module:
            return False
        return True


webhook = os.environ.get('SLACK_WEBHOOK')
sh = SlackHandler(webhook) if webhook else None

def init():
    if sh:
        sh.setFormatter(SlackFormatter())
        sh.setLevel(logging.DEBUG)
        filter = MyFilter()
        sh.addFilter(filter)
        logging.basicConfig(handlers=[sh])
