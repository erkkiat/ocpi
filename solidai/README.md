# solidai / NAP charging-session monitor

Approximates EV charging session durations in Finland by polling the
National Access Point's real-time status feed, because the NAP does not
publish actual charging sessions or CDRs.

## Background

- **Public via NAP**: static + real-time EVSE status (location, power,
  price, `AVAILABLE`/`CHARGING`/`OCCUPIED`/...), published by Fintraffic's
  Digitraffic AFIR API. Free, no auth, CC BY 4.0 licensed (commercial use
  allowed with attribution).
- **Not public**: actual charging sessions/CDRs (start/end time, kWh,
  cost, session id). That data is private OCPI traffic between the CPO
  (e.g. Virta) and an eMSP under a roaming agreement, and is not exposed
  through the NAP.

This script bridges the gap by watching the public status feed and
inferring session start/end from `CHARGING` status transitions per EVSE.

## Usage

```bash
python3 nap_session_monitor.py --db nap_sessions.db --interval 60
```

Sessions land in the `sessions` table of the SQLite DB (`--db`):
`evse_id`, `location_id`, `start_time`, `end_time`, `duration_seconds`,
`end_status`, plus the required `attribution` string for the CC BY 4.0
license.

Use `--once` for a single poll (smoke-testing / cron), `-v` for debug
logging.

## Limitations (read before relying on this data)

- **Estimate, not ground truth.** Duration = time between observed status
  transitions; accuracy is bounded by `--interval`. Sessions shorter than
  the poll interval can be missed entirely.
- **No session id, kWh, or cost** - only a duration estimate per EVSE.
- **No user/token identity.**
- Network blips or transient API errors can look like a spurious
  start/stop; there's no de-bounce/filtering beyond the raw status diff.
- Field names in `iter_evse_statuses()` (`nap_session_monitor.py`) are
  based on Fintraffic's public documentation and the OCPI status model,
  **not verified against a live response** - this was written in a
  sandbox whose network egress policy blocks `*.digitraffic.fi`. Before
  relying on this, run `--once -v` against the real API and check the
  parsed fields match; adjust `iter_evse_statuses()` if not. Also
  double-check `DEFAULT_BASE_URL` against the current docs at
  <https://www.digitraffic.fi/en/road-traffic/afir/>.

## License compliance

Digitraffic data is CC BY 4.0. Every exported session row includes the
attribution string; if you republish or build on this data downstream,
keep that attribution alongside it (see the earlier discussion in this
session for the exact CC BY 4.0 requirements - credit, license link,
indicate changes).
