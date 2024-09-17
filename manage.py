#!/usr/bin/env python
import os
import sys

# Refactor this part
if not os.environ.get("HOSTNAME"):
    from dotenv import load_dotenv

    load_dotenv()

if __name__ == "__main__":
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise ValueError("Django settings module has been not set please set it first")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
