import os

import cronitor

cronitor.api_key = os.environ.get("CRONITOR_API_KEY")

hostname = os.environ.get("HOSTNAME").split(".")[0]
monitor = cronitor.Monitor(hostname)
