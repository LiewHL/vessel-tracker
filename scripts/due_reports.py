"""Which reports are due? Lets the hourly logger start reports, since GitHub's own timer is unreliable.

  python scripts/due_reports.py list           print the kinds due now (weekly monthly quarterly)
  python scripts/due_reports.py check <kind>   exit 0 if that report is still due, 10 if already made

Needs the unlocked reports/index.json. Times are Singapore time.
  weekly     due from Monday 07:50 until Wednesday, if no weekly report dated this Monday or later
  monthly    due from the 1st 08:20 until the 7th, if last month's report is missing
  quarterly  due from the 1st of Jan/Apr/Jul/Oct 08:30 until the 14th, if last quarter's is missing
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
    index = read_json(REPORT_INDEX, [])
    made = {(r.get("kind", "weekly"), r.get("date", "")) for r in index}
    if kind == "weekly":
        monday = today - timedelta(days=today.weekday())
        if today.weekday() > 2 or now < datetime.combine(monday, time(7, 50), SGT):
            return False
        return not any(k == "weekly" and d >= monday.isoformat() for k, d in made)
    if kind == "monthly":
        if today.day > 7 or now < datetime.combine(today.replace(day=1), time(8, 20), SGT):
            return False
        prev = today.replace(day=1) - timedelta(days=1)
        return ("monthly", f"{prev:%Y-%m}") not in made
    if kind == "quarterly":
        if today.month not in (1, 4, 7, 10) or today.day > 14 \
                or now < datetime.combine(today.replace(day=1), time(8, 30), SGT):
            return False
        q = (today.month - 1) // 3
        y, q = (today.year, q) if q else (today.year - 1, 4)
        return ("quarterly", f"{y}-Q{q}") not in made
    return False


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        print(" ".join(k for k in ("weekly", "monthly", "quarterly") if due(k)))
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        return 0 if due(sys.argv[2]) else 10
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
