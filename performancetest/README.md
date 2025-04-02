# Performance Testing for OCPI Connector

This directory contains tools and scripts for performance testing the OCPI Connector service. The tests use [Locust](https://locust.io/) to simulate multiple charging sessions and API interactions simultaneously.

## Setup

1. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Make sure your OCPI Connector server is properly configured with a "performance" user (see authentication in the locustfile.py).

## How to Run the Performance Tests

### Step 1: Start the Server in Performance Mode

Start the OCPI Connector server using the provided script:

```bash
./gunicorn-run.sh [PORT]
```

Where:
- `[PORT]` is optional and defaults to 8000

This script:
- Sets environment variables from `.env-[PORT]`
- Enables performance testing mode with `PERFORMANCE_TEST=1`
- Disables sending updates with `SEND_UPDATES=0`
- Configures the CPO simulator with `CPO_SIMULATOR=1`
- Starts Gunicorn with 17 workers for better concurrency

### Step 2: Start the Locust Test Runner

Run the Locust test using one of the provided scripts:

For CPO testing (charging sessions):
```bash
./locust-run.sh
```

For MSP testing (mobile app API usage):
```bash
./locust-run-msp.sh
```

The scripts will start Locust with the host set to `http://localhost:8000`. You can pass additional Locust parameters to configure the test load.

### Step 3: Configure and Monitor the Test

1. Open your browser and navigate to http://localhost:8089 to access the Locust web interface.
2. Set the URL of the tested host in the "Host" field
3. From the tested host, select a MSP roaming partner you want to simulate, and get the base64 encoded token from the field "OCPI token for receiving" and paste it to the "OCPI Token" field.
3. Set the number of charging sessions to simulate and the spawn rate.
4. Start the test and monitor the results in real-time.

## What the Tests Do

### How the Framework Works

The performance test framework is built on Locust, which is designed for load testing:

1. **Distributed Testing Model**:
   - Each virtual user (VU) runs independently in its own execution context
   - VUs are distributed across worker processes for efficient parallel execution
   - A central controller coordinates the VUs and collects statistics

2. **Test Execution Flow**:
   - The `on_test_start` event handler runs once when the test begins
   - Multiple VUs are spawned according to the configured rate
   - Each VU executes its tasks in a continuous loop with configured wait times
   - The `on_stop` method runs when a VU completes or is terminated
   - The `on_test_stop` event handler runs once when the entire test ends

3. **Statistics Collection**:
   - Response times, failure rates, and throughput are automatically measured
   - Results are aggregated in real-time and displayed in the web UI
   - The percentile distribution shows performance consistency

### CPO Simulation (locustfile.py)

This test simulates concurrent charging sessions:

1. **Setup Phase** (`on_test_start` function):
   - Authenticates with the API to get a JWT token
   - Creates a test location with ID "PERFORMANCETEST"
   - Configures shared test data and authentication headers

2. **Per Charging Session** (`OCPIPartner` class):
   - Each simulated "user" in Locust represents a complete charging session on an EVSE
   - Key methods:
     - `test_session`: Main task that orchestrates a complete charging session
     - `get_available_evse`: Allocates an available EVSE from the pool
     - `create_evse`: Creates the EVSE via the CPO API if needed
     - `start_msp_session`: Initiates a session via the MSP API (OCPI command)
     - `start_cpo_session`: Starts the actual charging session on the CPO side
     - `set_charger_status`: Updates the EVSE status (Available→Charging→Available)
     - `update_kwh`: Sends periodic meter values updates during charging
     - `stop_cpo_session`: Ends the charging session on the CPO side
     - `free_up_evse`: Returns the EVSE to the pool for reuse

3. **Session Workflow**:
   - The `test_session` method simulates a full charging lifecycle:
     1. Acquires an EVSE from the pool
     2. Creates or verifies the EVSE exists
     3. Initiates a charging session via OCPI (MSP to CPO)
     4. Starts the actual charging session in the CPO system
     5. Changes EVSE status to "CHARGING"
     6. Sends 30-60 meter value updates at fixed intervals
     7. Stops the charging session
     8. Changes EVSE status back to "AVAILABLE"
     9. Returns the EVSE to the available pool

4. **Cleanup Phase** (`on_test_stop` function and `on_stop` method):
   - Ensures any active charging sessions are stopped
   - Resets all EVSEs back to "AVAILABLE" status
   - Resets the EVSE availability states

The test simulates a complete charging session lifecycle with realistic delays between actions.

### MSP Simulation (locustfile-msp.py)

This simpler test focuses on the MSP (Mobility Service Provider) API:

- Uses the `MobileApp` class to simulate mobile app clients
- The `get_map` task repeatedly requests the map locations endpoint 
- Simulates the typical load pattern of multiple users browsing for charging stations
- Uses wait times between 2-3 seconds to represent realistic usage patterns

## Configuration Options

- `EVSE_COUNT`: Maximum number of charging stations to simulate (default: 10,000)
- `METER_VALUES_INTERVAL`: Seconds between meter value updates (default: 20)
- `--ocpi-token`: OCPI token for authentication when sending remote commands

## Performance Considerations

- The tests are designed to evaluate the system's performance under various loads
- Each simulated "user" in Locust represents a complete charging session on an EVSE
- Monitor server resources (CPU, memory, database connections) during tests
- The default configuration simulates realistic charging scenarios with intervals between actions

### Architecture Details

- **Resource Management**: 
  - The tests use a shared pool of EVSEs to simulate realistic resource constraints
  - The `evses_available` array tracks which EVSEs are in use to avoid conflicts
  - EVSEs are dynamically created when needed and recycled after use

- **Realistic Simulation**:
  - Random delays and duration variations simulate real-world usage patterns
  - Charging sessions have varying lengths (30-60 kWh, 1 kWh per meter values)
  - Multiple API interactions per session test different system components

- **Test Design Principles**:
  - Follows the complete lifecycle of a charging session
  - Tests both synchronous API calls and asynchronous events
  - Exercises both MSP and CPO endpoints to test bi-directional communication
  - Uses realistic data volumes to reveal potential bottlenecks

### Measuring Performance

When analyzing results, focus on:
- Response times for critical operations (session start/stop)
- System stability under concurrent sessions
- Database performance with many sessions
- Resource consumption patterns
- Failure patterns when approaching system limits

## Troubleshooting

If you encounter issues:
1. Check the server logs for errors
2. Verify the authentication credentials match your system configuration
3. Adjust the number of simulated charging sessions if the system becomes overloaded
4. Make sure the `.env-[PORT]` file exists with proper configuration values
