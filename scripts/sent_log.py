import glob
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPORT_INDEX, REPORTS_DIR, read_json, write_json


KEEP = ("kind", "date", "sent", "by", "generated")


def tidy(index):
    out = []
    for r in index:
        r = {k: r[k] for k in KEEP if r.get(k)}
        r.setdefault("kind", "weekly")
        if not r.get("sent") and r.get("generated"):
            r["sent"] = r["generated"]
        if r.get("sent"):
            out.append(r)
    return sorted(out, key=lambda r: r["sent"], reverse=True)[:200]


def main():
    if sys.argv[1:] == ["--tidy"]:
        before = read_json(REPORT_INDEX, None)
        if before is not None:
            after = tidy(before)
            if after != before:
                write_json(REPORT_INDEX, after)
                print("Sent log tidied.")
        return 0
    kind, date = sys.argv[1], sys.argv[2]
    opts = dict(zip(sys.argv[3::2], sys.argv[4::2]))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index = read_json(REPORT_INDEX, [])
    if opts.get("--request"):
        built = next((dict(r) for r in index if r.get("kind", "weekly") == kind and r.get("date") == date), {"kind": kind, "date": date})
        backup = opts.get("--backup", "")
        index = read_json(backup, []) if backup and os.path.exists(backup) else \
            [r for r in index if not (r.get("kind", "weekly") == kind and r.get("date") == date and not r.get("by"))]
        built.update({"sent": now, "by": opts["--request"].upper()})
        index = sorted([built] + index, key=lambda r: (r.get("date", ""), r.get("sent", "")), reverse=True)
    for r in index:
        if not opts.get("--request") and r.get("kind", "weekly") == kind and r.get("date") == date and not r.get("by"):
            r["sent"] = now
    write_json(REPORT_INDEX, tidy(index))
    for pat in ("*.html", "*.md"):
        for p in glob.glob(os.path.join(REPORTS_DIR, pat)):
            os.remove(p)
    print(f"Logged as sent: {kind} {date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
