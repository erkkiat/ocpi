import uuid
from datetime import datetime
from random import randint
from time import sleep
from typing import Optional, Union


import pytz
import requests
from locust import HttpUser, task, events, between
from locust.env import Environment

EVSE_COUNT = 10000
METER_VALUES_INTERVAL = 20
LOCATION_ID = "PERFORMANCETEST"
evses_available = [True for x in range(EVSE_COUNT + 1)]
basic_auth = requests.auth.HTTPBasicAuth("performance", "password")
token = "NOT YET AVAILABLE"
headers = {}


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument(
        "--ocpi-token",
        type=str,
        env_var="OCPI_TOKEN",
        default="",
        help="The OCPI token_b used for authentication when sending remote commands",
    )
    # Choices will validate command line input and show a dropdown in the web UI
    # parser.add_argument("--env", choices=["dev", "staging", "prod"], default="dev", help="Environment")
    # Set `include_in_web_ui` to False if you want to hide from the web UI
    # parser.add_argument("--my-ui-invisible-argument", include_in_web_ui=False, default="I am invisible")
    # Set `is_secret` to True if you want the text input to be password masked in the web UI
    # parser.add_argument("--my-ui-password-argument", is_secret=True, default="I am a secret")


def create_evse(environment: Environment, location_id: str, evse_uid: Union[int, str]):
    assert token, "Token not available (yet)"

    print(f"Creating EVSE #{evse_uid}")
    data = {
        "id": location_id,
        "evses": [
            {
                "uid": str(evse_uid),
                "connectors": [
                    {
                        "uid": "1",
                        "standard": "IEC_62196_T2",
                        "format": "CABLE",
                        "max_voltage": 240,
                        "max_amperage": 32,
                        "tariff_ids": ["T1"],
                        "last_updated": "2022-01-08T14:15:25Z",
                    }
                ],
                "last_updated": "2022-01-08T14:15:25.972000Z",
            }
        ],
    }

    response = requests.put(
        f"{environment.host}/api/cpo/v2/location/quick/", json=data, headers=headers
    )
    assert response.status_code in (
        200,
        201,
    ), f"Failed to create EVSE: {response.status_code}, {response.text}"


def create_location(environment: Environment, location_id: str):
    assert token, "Token not available (yet)"

    data = {
        "id": location_id,
        "name": "Performance test location",
        "address": "Performance street 1",
        "city": "Lahti",
        "country": "FIN",
        "time_zone": "Europe/Helsinki",
        "latitude": 60.0,
        "longitude": 23.0,
    }

    response = requests.put(
        f"{environment.host}/api/cpo/v2/location/quick/", json=data, headers=headers
    )
    assert response.status_code in (
        200,
        201,
    ), f"Failed to create location: {response.status_code}, {response.text}"


@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs):
    global token
    global headers

    # Get the JWT token
    response = requests.post(
        f"{environment.host}/api/token/pair",
        json={"username": "performance", "password": "password", "exp": 86400},
    )

    token = response.json().get("access")
    assert (
        len(token) > 10
    ), f"Failed to get token: {response.status_code}, {response.text}"
    headers = {"Authorization": f"Bearer {token}"}

    create_location(environment, LOCATION_ID)
    # for i in range(451, EVSE_COUNT+1):
    #     create_evse(environment, LOCATION_ID, i)


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **kwargs):
    global evses_available
    evses_available = [True for x in range(EVSE_COUNT + 1)]


def get_available_evse() -> Optional[int]:
    for i in range(1, EVSE_COUNT + 1):
        if evses_available[i]:
            evses_available[i] = False
            print(f"Reserving EVSE #{i}")
            return i
    return None


def free_up_evse(uid) -> bool:
    if uid > EVSE_COUNT:
        return False
    evses_available[uid] = True
    print(f"Freeing up EVSE #{uid}")


class OCPIPartner(HttpUser):
    wait_time = between(2, 3)
    user_id = None
    session_id = None
    evse_uid = None

    def on_start(self):
        self.user_id = uuid.uuid4().hex[:4]

    def on_stop(self):
        sleep(randint(10, 70) / 10)  # All users should not stop at the same time
        if self.session_id:
            self.stop_cpo_session(self.session_id)
        sleep(randint(10, 70) / 10)
        if self.evse_uid:
            free_up_evse(self.evse_uid)
            self.set_charger_status(self.evse_uid, "AVAILABLE")

    # @task
    # def get_versions(self):
    #     self.client.get("/ocpi/versions/")
    #     self.client.get("/ocpi/2.2.1/")

    def set_charger_status(self, evse_uid: Union[str, int], status: str):
        response = self.client.post(
            "/api/cpo/v2/chargepoint/status_change/",
            json=dict(evse_uid=str(evse_uid), status=status),
            headers=headers,
        )
        assert response.status_code in (
            200,
            201,
        ), f"Failed to set charger {evse_uid} status: {response.status_code}"
        print(f"Set charger {evse_uid} status to {status}")

    def update_kwh(self, session_id: str, kwh: float):
        response = self.client.post(
            "/api/cpo/v3/charging/meter_values/",
            # "/api/cpo/v2/chargepoint/meter_values/",
            json=dict(
                session_id=session_id, kwh=kwh, soc=kwh + 40, power=randint(40, 60)
            ),
            headers=headers,
        )
        assert response.status_code in (
            200,
            201,
        ), f"Failed to set session {session_id} to {kwh} kWh: {response.status_code}"
        print(f"Session {session_id} updated with {kwh} kWh")

    def start_msp_session(self, evse_uid, ocpi_token=None):
        token_id = f"USER-{uuid.uuid4().hex[:16]}"
        authorization = uuid.uuid4().hex[:6]
        data = {
            "location_id": LOCATION_ID,
            "authorization_reference": f"FI*000*A*{authorization}",
            "evse_uid": evse_uid,
            "connector_id": "1",
            "token": {
                "uid": token_id,
                "type": "APP_USER",
                "contract_id": "N/A",
                "party_id": "001",
                "country_code": "FI",
            },
            "response_url": f"{self.environment.host}/ocpi/2.2.1/commands/COMMAND_RESULT/start/{authorization}",
        }
        response = self.client.post(
            "/ocpi/2.2.1/commands/START_SESSION",
            json=data,
            headers={
                "Ocpi-From-Country-Code": "FI",
                "Ocpi-From-Party-Id": "001",
                # 'Content-Type': 'application/json',
                "Authorization": f"Token {ocpi_token}",
            },
        )
        assert (
            response.status_code in (200, 201)
        ), f"Failed to send remote command start charging for EVSE #{evse_uid}: {response.status_code} {response.text}"
        return token_id

    def start_cpo_session(self, evse_uid, token_id):
        response = self.client.post(
            "/api/cpo/v3/charging/start/",
            # "/api/cpo/v2/chargepoint/start_transaction/",
            json=dict(evse_uid=str(evse_uid), connector_id="1", token_id=token_id),
            headers=headers,
        )
        assert (
            response.status_code in (200, 201)
        ), f"Failed to start CPO session for EVSE {evse_uid} token {token_id}: {response.status_code}, {response.text}"
        print(f"Started CPO session at EVSE #{evse_uid} with token {token_id}")
        return response.json()["session"]["session_id"]

    def stop_cpo_session(self, session_id):
        response = self.client.post(
            "/api/cpo/v3/charging/stop/",
            # "/api/cpo/v2/chargepoint/stop_transaction/",
            json=dict(
                session_id=session_id, stop_timestamp=datetime.now(pytz.utc).isoformat()
            ),
            headers=headers,
        )
        assert response.status_code in (
            200,
            201,
        ), f"Failed to stop CPO session {session_id}: {response.status_code}"
        print(f"Stopped CPO session {session_id}")

    @task
    def test_session(self):
        self.evse_uid = get_available_evse()
        print(f"Starting session with EVSE UID: {self.evse_uid}")
        if not self.evse_uid:
            return

        create_evse(self.environment, LOCATION_ID, self.evse_uid)

        ocpi_token = self.environment.parsed_options.ocpi_token
        token_id = self.start_msp_session(self.evse_uid, ocpi_token=ocpi_token)
        print(f"Remote started session with token {token_id}")

        sleep(randint(2, 4))

        self.session_id = self.start_cpo_session(self.evse_uid, token_id)
        print(f"Started CPO session with ID {self.session_id}")

        # Set charger status to charging
        self.set_charger_status(self.evse_uid, "CHARGING")

        # Meter values
        for i in range(1, randint(30, 60)):
            self.update_kwh(self.session_id, i)
            sleep(METER_VALUES_INTERVAL)

        # Stop session
        self.stop_cpo_session(self.session_id)
        self.session_id = None

        # Set charger status to available
        self.set_charger_status(self.evse_uid, "AVAILABLE")

        free_up_evse(self.evse_uid)
