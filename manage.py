#!/usr/bin/env python
import os
import sys

from dotenv import load_dotenv


def _load_envs():
    base_dir = os.getcwd()
    env_path = os.path.join(base_dir, ".env")
    load_dotenv(env_path)


if __name__ == "__main__":
    _load_envs()
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise ValueError("Django settings module has been not set please set it first")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise ValueError("Django settings module has been not set please set it first")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
