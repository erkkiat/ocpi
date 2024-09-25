#!/usr/bin/env python3

import json
import os
import subprocess
import sys


def set_heroku_remote(app_name):
    subprocess.run(["heroku", "git:remote", "-a", app_name], check=True)


def set_buildpack(app_name):
    subprocess.run(
        ["heroku", "buildpacks:set", "heroku/python", "-a", app_name], check=True
    )


def create_addon(app_name):
    subprocess.run(
        ["heroku", "addons:create", "heroku-postgresql:hobby-dev", "-a", app_name],
        check=True,
    )


def set_config_var(app_name, github_token):
    subprocess.run(
        ["heroku", "config:set", f"GITHUB_TOKEN={github_token}", "-a", app_name],
        check=True,
    )


def main():
    # Parse the input from Terraform
    input_json = sys.stdin.read()
    input_data = json.loads(input_json)

    app_name = input_data["app_name"]
    github_repo = input_data["github_repo"]
    github_token = os.getenv(
        "GITHUB_TOKEN", ""
    )  # Replace with your method of securing the token

    if not github_token:
        raise ValueError("The GITHUB_TOKEN environment variable is not set.")

    set_heroku_remote(app_name)
    set_buildpack(app_name)
    create_addon(app_name)
    set_config_var(app_name, github_token)

    # Output the result in JSON format
    output_data = {"app_name": app_name, "github_repo": github_repo}
    print(json.dumps(output_data))


if __name__ == "__main__":
    main()
