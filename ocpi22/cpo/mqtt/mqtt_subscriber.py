import os
import sys
from logging import getLogger

import django
from dotenv import load_dotenv

logger = getLogger(__name__)


def _load_envs():
    environment = os.getenv("ENV")
    if environment in ["test", "development"]:
        current_directory = os.getcwd()
        env_path = os.path.join(current_directory, "test.env")
        load_dotenv(env_path)
        logger.info("Loaded test.env from root")
    else:
        logger.info("Skipping dotenv for production and staging")


def setup_django():
    _load_envs()
    sys.path.append(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    )

    # Set the Django settings module
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ocpiconnector.settings.dev")
    django.setup()


def main():
    setup_django()

    from ocpi22.cpo.mqtt.mqtt_client import MQTTClientSingleton
    from ocpiconnector.settings.base import env_bool

    logger = getLogger(__name__)
    loop_forever = env_bool("MQTT_LOOP_FOREVER", True)
    mqtt_singleton = MQTTClientSingleton()

    try:
        mqtt_singleton.start_client(loop_forever)
    except KeyboardInterrupt:
        logger.info("Shutting down MQTT client...")
        mqtt_singleton.reset_client()
    except Exception as e:
        logger.error(f"Error running MQTT client: {e}")
        mqtt_singleton.reset_client()
        raise


if __name__ == "__main__":
    main()
