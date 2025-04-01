from locust import HttpUser, task, events, between
from locust.env import Environment
from requests.auth import HTTPBasicAuth

basic_auth = HTTPBasicAuth("performance", "password")


@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs):
    pass


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **kwargs):
    pass


class MobileApp(HttpUser):
    wait_time = between(2, 3)

    def on_start(self):
        pass

    @task
    def get_map(self):
        self.client.get("/api/msp/v1/map/locations/")
