"""Which reports are due? Lets the hourly logger start reports, since GitHub's own timer is unreliable.

  python scripts/due_reports.py list           print the kinds due now (weekly monthly quarterly)
  python scripts/due_reports.py check <kind>   exit 0 if that report is still due, 10 if already made
  python scripts/due_reports.py request S3     exit 0 if staff S3 may still use Send today, 10 if not
                                               (at most 5 a day; Singapore days)

Needs the unlocked reports/index.json. Times are Singapore time.
  quarterly  due from the 1st of Jan/Apr/Jul/Oct 06:00 until the 14th, if last quarter's is missing
  monthly    due from the 1st 07:00 until the 7th, if last month's report is missing
  weekly     due from Monday 08:00 until Wednesday, if no weekly report dated this Monday or later
The hourly logger (on the hour, 15-minute listen) starts one due report per run, so they go out
at about 06:15, 07:15 and 08:15.
"""
import os
import sys
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPORT_INDEX, read_json  # noqa: E402

SGT = timezone(timedelta(hours=8))


def due(kind, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(SGT)
    today = now.date()
    # Reports sent with the Send button ("by": S3) don't count: the scheduled one still goes out.
    index = [r for r in read_json(REPORT_INDEX, []) if not r.get("by")]
    made = {(r.get("kind", "weekly"), r.get("date", "")) for r in index}
    # A monthly/quarterly report made before its period ended (e.g. a test run) doesn't count:
    # the complete one is still due.
    final = {(r.get("kind"), r.get("date", "")) for r in index
             if r.get("generated", "9999") >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
             .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if kind == "weekly":
        monday = today - timedelta(days=today.weekday())
        if today.weekday() > 2 or now < datetime.combine(monday, time(8, 0), SGT):
            return False
        return not any(k == "weekly" and d >= monday.isoformat() for k, d in made)
    if kind == "monthly":
        if today.day > 7 or now < datetime.combine(today.replace(day=1), time(7, 0), SGT):
            return False
        prev = today.replace(day=1) - timedelta(days=1)
        return ("monthly", f"{prev:%Y-%m}") not in final
    if kind == "quarterly":
        if today.month not in (1, 4, 7, 10) or today.day > 14 \
                or now < datetime.combine(today.replace(day=1), time(6, 0), SGT):
            return False
        q = (today.month - 1) // 3
        y, q = (today.year, q) if q else (today.year - 1, 4)
        return ("quarterly", f"{y}-Q{q}") not in final
    return False


REQUESTS_PER_DAY = 5


def requests_today(slot, now=None):
    today = (now or datetime.now(timezone.utc)).astimezone(SGT).date()
    n = 0
    for r in read_json(REPORT_INDEX, []):
        if (r.get("by") or "").upper() == slot.upper() and r.get("sent"):
            t = datetime.strptime(r["sent"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            n += t.astimezone(SGT).date() == today
    return n


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        print(" ".join(k for k in ("quarterly", "monthly", "weekly") if due(k)))
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "request":
        return 0 if requests_today(sys.argv[2]) < REQUESTS_PER_DAY else 10
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        return 0 if due(sys.argv[2]) else 10
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
