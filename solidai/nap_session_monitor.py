#!/usr/bin/env python3
"""
NAP charging-session duration monitor (solidai)

The Finnish National Access Point (NAP) publishes EV charging infrastructure
data via Fintraffic's Digitraffic AFIR API. That API exposes only the
*current status* per EVSE (AVAILABLE, CHARGING, OCCUPIED, ...); it does not
expose charging sessions or CDRs (those are private OCPI data exchanged
directly between the CPO, e.g. Virta, and an eMSP under a roaming
agreement).

This tool approximates session duration by polling the status endpoint on
an interval and recording, per EVSE, the transitions into and out of the
CHARGING status. This is an *estimate*, bounded by the poll interval - it
has no access to the real session id, energy delivered or price.

Data source license: Digitraffic data is CC BY 4.0 (Fintraffic / digitraffic.fi).
Attribution is written into every exported/logged record; see README.md.

NOTE: this sandbox's network egress policy blocks *.digitraffic.fi, so this
script has not been exercised against the live API. The GeoJSON field names
below are inferred from Fintraffic's public documentation and OCPI's own
Location/EVSE status model, but should be verified against the current
Swagger docs (https://www.digitraffic.fi/en/road-traffic/afir/) and adjusted
in `iter_evse_statuses()` if they differ once you can reach the API.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Iterator, Optional

DEFAULT_BASE_URL = "https://tie.digitraffic.fi/api/charging-network/v1/locations/statuses"
ATTRIBUTION = "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY"

# OCPI EVSE status values that represent an EVSE actively delivering energy.
CHARGING_STATUSES = {"CHARGING"}

log = logging.getLogger("solidai.nap_session_monitor")


@dataclasses.dataclass
class EvseStatus:
    evse_id: str
    location_id: str
    status: str
    observed_at: str  # ISO-8601, from the API payload if present, else poll time


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_page(base_url: str, cursor: Optional[str], timeout: float) -> dict:
    url = base_url
    if cursor:
        url += ("&" if "?" in url else "?") + f"cursor={cursor}"
    req = urllib.request.Request(url, headers={"User-Agent": "solidai-nap-session-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_features(base_url: str, timeout: float) -> Iterator[dict]:
    """Follow cursor-based pagination and yield every GeoJSON feature."""
    cursor = None
    while True:
        try:
            payload = fetch_page(base_url, cursor, timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("fetch failed (cursor=%s): %s", cursor, exc)
            return
        for feature in payload.get("features", []):
            yield feature
        cursor = payload.get("nextCursor")
        if not cursor:
            return


def iter_evse_statuses(feature: dict, poll_time: str) -> Iterator[EvseStatus]:
    """
    Extract per-EVSE status from one GeoJSON feature (one charging location).

    Defensive about field naming since this hasn't been verified against a
    live response (see module docstring) - tries a couple of plausible key
    variants before giving up on a given EVSE entry.
    """
    props = feature.get("properties", {})
    location_id = str(props.get("id") or props.get("location_id") or feature.get("id") or "unknown")

    evses = props.get("evses") or props.get("evse") or []
    for evse in evses:
        evse_id = evse.get("id") or evse.get("uid") or evse.get("evse_id")
        if evse_id is None:
            continue

        status = evse.get("status")
        observed_at = evse.get("last_updated") or evse.get("time") or evse.get("timestamp") or poll_time

        if status is None:
            # Some feeds report status per-connector rather than per-EVSE.
            connectors = evse.get("connectors") or []
            statuses = {c.get("status") for c in connectors if c.get("status")}
            status = "CHARGING" if "CHARGING" in statuses else (next(iter(statuses), None) if statuses else None)

        if status is None:
            continue

        yield EvseStatus(
            evse_id=str(evse_id),
            location_id=location_id,
            status=str(status).upper(),
            observed_at=str(observed_at),
        )


class SessionStore:
    """SQLite-backed state so open sessions survive a restart."""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evse_state (
                evse_id TEXT PRIMARY KEY,
                location_id TEXT NOT NULL,
                status TEXT NOT NULL,
                since TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evse_id TEXT NOT NULL,
                location_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds REAL,
                end_status TEXT,
                source TEXT NOT NULL,
                attribution TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def get_previous(self, evse_id: str) -> Optional[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.execute("SELECT * FROM evse_state WHERE evse_id = ?", (evse_id,))
        return cur.fetchone()

    def upsert_state(self, evse_id: str, location_id: str, status: str, since: str):
        self.conn.execute(
            """
            INSERT INTO evse_state (evse_id, location_id, status, since)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(evse_id) DO UPDATE SET
                location_id = excluded.location_id,
                status = excluded.status,
                since = excluded.since
            """,
            (evse_id, location_id, status, since),
        )

    def open_session(self, evse_id: str, location_id: str, start_time: str):
        self.conn.execute(
            """
            INSERT INTO sessions (evse_id, location_id, start_time, source, attribution)
            VALUES (?, ?, ?, ?, ?)
            """,
            (evse_id, location_id, start_time, "nap-status-poll", ATTRIBUTION),
        )

    def close_open_session(self, evse_id: str, end_time: str, end_status: str):
        cur = self.conn.execute(
            """
            SELECT id, start_time FROM sessions
            WHERE evse_id = ? AND end_time IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (evse_id,),
        )
        row = cur.fetchone()
        if row is None:
            return
        session_id, start_time = row
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration = (end_dt - start_dt).total_seconds()
        except ValueError:
            duration = None
        self.conn.execute(
            """
            UPDATE sessions SET end_time = ?, duration_seconds = ?, end_status = ?
            WHERE id = ?
            """,
            (end_time, duration, end_status, session_id),
        )

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def process_snapshot(store: SessionStore, statuses: Iterator[EvseStatus]) -> tuple[int, int]:
    """Diff the latest snapshot against stored state; open/close sessions on transitions."""
    opened = closed = 0
    for evse in statuses:
        previous = store.get_previous(evse.evse_id)
        prev_status = previous["status"] if previous else None

        if evse.status == prev_status:
            continue  # no transition

        now_charging = evse.status in CHARGING_STATUSES
        was_charging = prev_status in CHARGING_STATUSES if prev_status else False

        if now_charging and not was_charging:
            store.open_session(evse.evse_id, evse.location_id, evse.observed_at)
            opened += 1
        elif was_charging and not now_charging:
            store.close_open_session(evse.evse_id, evse.observed_at, evse.status)
            closed += 1

        store.upsert_state(evse.evse_id, evse.location_id, evse.status, evse.observed_at)

    store.commit()
    return opened, closed


def run(base_url: str, db_path: str, interval: float, timeout: float, once: bool):
    store = SessionStore(db_path)
    log.info("%s", ATTRIBUTION)
    try:
        while True:
            poll_time = _now_iso()
            features = fetch_all_features(base_url, timeout)
            statuses = (s for f in features for s in iter_evse_statuses(f, poll_time))
            opened, closed = process_snapshot(store, statuses)
            log.info("poll @ %s: %d session(s) started, %d ended", poll_time, opened, closed)
            if once:
                break
            time.sleep(interval)
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="AFIR charging-network statuses endpoint")
    parser.add_argument("--db", default="nap_sessions.db", help="SQLite output path")
    parser.add_argument("--interval", type=float, default=60.0, help="Poll interval in seconds")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP request timeout in seconds")
    parser.add_argument("--once", action="store_true", help="Poll a single time and exit (for testing)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    run(args.base_url, args.db, args.interval, args.timeout, args.once)


if __name__ == "__main__":
    main()
