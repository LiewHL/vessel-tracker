"""Daily position logger.

Connects to AISStream (https://aisstream.io), listens for the ships listed in
vessels.csv for LISTEN_MINUTES, then saves the latest position of every ship
it heard to data/positions.csv (history) and data/latest.json (dashboard).

Environment variables
  AISSTREAM_API_KEY  required, set as a GitHub Actions secret
  LISTEN_MINUTES     optional, default 30
"""
import asyncio
import json
import os
import random
import sys
import time
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    LATEST, NAV_STATUS, RUN_LOG, STATUS, append_positions, iso, load_roster, now_utc,
    read_json, write_json,
)

STREAM_URL = "wss://stream.aisstream.io/v0/stream"
POSITION_TYPES = (
    "PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport",
)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ais_time(meta):
    """AISStream time_utc looks like '2026-10-17 01:02:03.123 +0000 UTC'."""
    raw = str(meta.get("time_utc") or meta.get("TimeUtc") or "")
    if len(raw) >= 19 and raw[4] == "-" and raw[10] == " ":
        return raw[:10] + "T" + raw[11:19] + "Z"
    return None


def valid_position(lat, lon):
    if lat is None or lon is None:
        return False
    if abs(lat) > 90 or abs(lon) > 180:      # 91 / 181 mean "not available"
        return False
    if lat == 0 and lon == 0:
        return False
    return True


def handle_message(msg, state, wanted):
    """Update `state` with one decoded AISStream message.

    state = {"positions": {mmsi: {...}}, "destinations": {mmsi: str}, "messages": int}
    Returns the MMSI the message belonged to, or None if ignored.
    """
    mtype = msg.get("MessageType")
    meta = msg.get("MetaData") or {}
    body = (msg.get("Message") or {}).get(mtype) or {}
    mmsi = str(meta.get("MMSI") or body.get("UserID") or "").strip()
    if not mmsi or mmsi not in wanted:
        return None
    state["messages"] += 1

    if mtype == "ShipStaticData":
        dest = str(body.get("Destination") or "").replace("@", "").strip()
        if dest:
            state["destinations"][mmsi] = dest
        return mmsi

    if mtype not in POSITION_TYPES:
        return None

    lat = _num(body.get("Latitude"))
    lon = _num(body.get("Longitude"))
    if not valid_position(lat, lon):
        lat = _num(meta.get("Latitude", meta.get("latitude")))
        lon = _num(meta.get("Longitude", meta.get("longitude")))
    if not valid_position(lat, lon):
        return None

    sog = _num(body.get("Sog"))
    cog = _num(body.get("Cog"))
    status = body.get("NavigationalStatus")
    fix = {
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "speed_kn": None if sog is None or sog >= 102.3 else round(sog, 1),
        "course_deg": None if cog is None or cog >= 360 else round(cog, 1),
        "nav_status": NAV_STATUS.get(status, "") if isinstance(status, int) else "",
        "ais_time_utc": _ais_time(meta) or iso(now_utc()),
        "ship_name_ais": str(meta.get("ShipName") or "").strip(),
    }
    prev = state["positions"].get(mmsi)
    if prev is None or fix["ais_time_utc"] >= prev["ais_time_utc"]:
        state["positions"][mmsi] = fix
    return mmsi


async def listen(api_key, mmsis, seconds, state):
    import websockets  # imported here so the parser can be tested without it

    deadline = time.monotonic() + seconds
    backoff = 2
    subscription = json.dumps({
        "APIKey": api_key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": mmsis,
        "FilterMessageTypes": list(POSITION_TYPES) + ["ShipStaticData"],
    })
    wanted = set(mmsis)

    while time.monotonic() < deadline:
        try:
            async with websockets.connect(
                STREAM_URL, compression="deflate", open_timeout=20,
                ping_interval=20, ping_timeout=20, max_size=2 ** 22,
            ) as ws:
                await ws.send(subscription)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        return
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "replace")
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if "error" in msg:
                        state["errors"].append(str(msg["error"])[:200])
                        break
                    if msg.get("MessageType") == "SubscriptionConfirmation":
                        state["connected"] = True   # key accepted
                        backoff = 2
                        continue
                    handle_message(msg, state, wanted)
        except Exception as exc:  # network drops, server closes, etc.
            state["errors"].append(f"{type(exc).__name__}: {str(exc)[:160]}")
        state["reconnects"] += 1
        wait = min(backoff, max(0.0, deadline - time.monotonic()))
        if wait <= 0:
            return
        await asyncio.sleep(wait + random.uniform(0, 1))
        backoff = min(backoff * 2, 60)


def schedule_delay(started):
    """Minutes between the planned schedule minute and the actual start (scheduled runs only)."""
    if os.environ.get("RUN_TRIGGER") != "schedule":
        return None
    try:
        minute = int(os.environ.get("SCHEDULE_MINUTE", "17"))
    except ValueError:
        return None
    planned = started.replace(minute=minute, second=0, microsecond=0)
    if planned > started:
        planned -= timedelta(hours=1)
    return round((started - planned).total_seconds() / 60, 1)


def save_results(roster, state, started, listen_minutes, status):
    run_time = now_utc()
    by_mmsi = {v["mmsi"]: v for v in roster if v["mmsi"]}
    latest = read_json(LATEST, {})
    rows = []
    for mmsi, fix in state["positions"].items():
        v = by_mmsi.get(mmsi)
        if not v:
            continue
        dest = state["destinations"].get(mmsi, latest.get(v["id"], {}).get("destination", ""))
        row = {
            "logged_at_utc": iso(run_time), "id": v["id"], "vessel_name": v["vessel_name"],
            "mmsi": mmsi, "latitude": fix["latitude"], "longitude": fix["longitude"],
            "speed_kn": "" if fix["speed_kn"] is None else fix["speed_kn"],
            "course_deg": "" if fix["course_deg"] is None else fix["course_deg"],
            "nav_status": fix["nav_status"], "destination": dest,
            "ais_time_utc": fix["ais_time_utc"],
        }
        rows.append(row)
        latest[v["id"]] = {
            "id": v["id"], "vessel_name": v["vessel_name"], "mmsi": mmsi, "imo": v["imo"],
            "latitude": fix["latitude"], "longitude": fix["longitude"],
            "speed_kn": fix["speed_kn"], "course_deg": fix["course_deg"],
            "nav_status": fix["nav_status"], "destination": dest,
            "last_seen_utc": fix["ais_time_utc"], "ship_name_ais": fix["ship_name_ais"],
        }
    rows.sort(key=lambda r: r["id"])
    if rows:
        append_positions(rows)
    write_json(LATEST, latest)

    log = read_json(RUN_LOG, {})
    entry = {
        "run_utc": iso(run_time), "status": status, "listen_minutes": listen_minutes,
        "trigger": os.environ.get("RUN_TRIGGER", "manual"), "started_utc": iso(started),
        "start_delay_min": schedule_delay(started),
        "vessels_tracked": len(by_mmsi), "vessels_heard": len(rows),
        "heard_ids": [r["id"] for r in rows], "messages": state["messages"],
        "reconnects": state["reconnects"], "errors": state["errors"][-5:],
    }
    history = ([entry] + log.get("history", []))[:240]
    write_json(RUN_LOG, {
        "last_run_utc": entry["run_utc"], "last_status": status,
        "started_utc": iso(started), "history": history,
    })
    write_status(entry)
    return entry


def write_status(entry):
    """data/status.json stays readable (not locked) so run health can be checked without the
    passcode. It holds counts and times only: never IDs, names or positions."""
    old = read_json(STATUS, {})
    keep = ("run_utc", "status", "trigger", "start_delay_min", "listen_minutes",
            "vessels_tracked", "vessels_heard", "messages", "reconnects")
    item = {k: entry.get(k) for k in keep}
    history = ([item] + old.get("history", []))[:240]
    write_json(STATUS, {"last_run_utc": entry["run_utc"], "last_status": item["status"], "history": history})


def main():
    started = now_utc()
    listen_minutes = float(os.environ.get("LISTEN_MINUTES") or 30)
    roster = load_roster()
    mmsis = sorted({v["mmsi"] for v in roster if len(v["mmsi"]) == 9})
    bad = [v["id"] for v in roster if len(v["mmsi"]) != 9]
    if bad:
        print(f"Warning: {len(bad)} ship(s) have no valid 9-digit MMSI and are skipped (see vessels.csv).")
    state = {"positions": {}, "destinations": {}, "messages": 0,
             "reconnects": 0, "errors": [], "connected": False}

    api_key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not api_key:
        entry = save_results(roster, state, started, listen_minutes, "error: AISSTREAM_API_KEY secret is missing")
        print(entry["status"])
        return 1
    if not mmsis:
        entry = save_results(roster, state, started, listen_minutes, "error: no valid MMSI numbers in vessels.csv")
        print(entry["status"])
        return 1

    print(f"Listening for {len(mmsis)} ships for {listen_minutes:g} minutes...")
    asyncio.run(listen(api_key, mmsis, listen_minutes * 60, state))
    if not state["connected"]:
        status = "error: AISStream did not accept the connection (check the API key)"
    elif state["positions"]:
        status = "ok"
    else:
        status = "ok: no ships heard this run"
    entry = save_results(roster, state, started, listen_minutes, status)
    # Public run logs show counts only: no IDs, names or positions.
    print(f"{status} | heard {entry['vessels_heard']} of {entry['vessels_tracked']} ships, "
          f"{entry['messages']} AIS messages, {entry['reconnects']} reconnects")
    return 0 if state["connected"] else 1


if __name__ == "__main__":
    sys.exit(main())
