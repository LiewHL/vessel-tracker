"""Daily logger health check: email if the logger has not run for 24 hours or its last run failed.

Reads data/status.json (counts and times only, not locked). Prints no addresses.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import STATUS, now_utc, parse_iso, read_json  # noqa: E402
from insights import SGT  # noqa: E402
import notify  # noqa: E402

MAX_HOURS = 24


def main():
    st = read_json(STATUS, {})
    last = parse_iso(st.get("last_run_utc"))
    status = str(st.get("last_status", ""))
    hours = (now_utc() - last).total_seconds() / 3600 if last else None
    problems = []
    if hours is None:
        problems.append("The logger has no recorded run.")
    elif hours > MAX_HOURS:
        problems.append(f"The logger has not run for {hours:.0f} hours (last run {last.astimezone(SGT):%d %b %H:%M} SGT).")
    if status and not status.startswith("ok"):
        problems.append(f"The last run reported a problem: {status}")
    if not problems:
        print(f"Logger healthy: last run {hours:.1f} h ago.")
        return 0
    body = "\n".join(problems + [
        "",
        "What to check:",
        "- GitHub > your project > Actions > Daily position log: is it enabled, and did recent runs fail?",
        "- A red run at 'Unlock the data' means the REPORT_PASSCODE secret is missing or was changed.",
        "- An AISStream error means the AISSTREAM_API_KEY secret needs checking.",
        "- GitHub sometimes delays or skips scheduled runs; Run workflow starts one by hand.",
    ])
    notify.send("Vessel tracker: logger needs attention", body)
    print(f"Logger problem found ({len(problems)}); alert sent if email is set up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
