import logging
import os

from slack_logger import SlackHandler, SlackFormatter

webhook = os.environ.get('SLACK_WEBHOOK')
sh = SlackHandler(webhook) if webhook else None


def init():
    if sh:
        sh.setFormatter(SlackFormatter())
        sh.setLevel(logging.DEBUG)
        logging.basicConfig(handlers=[sh])
