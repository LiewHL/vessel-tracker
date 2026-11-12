import html
from datetime import timedelta

from common import REQUIRED_DAYS, completion_date, period_info

HEADER = ["Code", "Vessel", "Category", "Group", "Days on board", "Days left",
          "Completed on / expected", "Paused since", "Resumes", "Expected in range"]


def gather(roster, start, end, today):
    """Completed between start and min(end, today); when end is in the future, also who is expected to complete by then."""
    done, expected, paused, due = [], [], [], []
    fut0 = max(start, today + timedelta(days=1))
    for v in roster:
        st = v.get("stints", [])
        p = period_info(st, today)
        d = completion_date(st)
        if d and start <= d <= min(end, today):
            done.append((d, v))
        e = p["expected_end"]
        if e and fut0 <= e <= end and (p["status"] == "onboard" or p["next_start"]):
            due.append((e, v, p))
        if p["status"] == "onboard" and p["expected_end"]:
            expected.append((p["expected_end"], v, p["days"]))
        elif p["status"] == "paused" or (p["status"] == "upcoming" and p["days"] > 0):
            paused.append((v, p))
    cat = lambda v: (v.get("category") or "").strip() or "No category"
    done.sort(key=lambda x: (x[0], x[1]["id"]))
    expected.sort(key=lambda x: (x[0], x[1]["id"]))
    paused.sort(key=lambda x: (cat(x[0]), x[0]["id"]))
    due.sort(key=lambda x: (x[0], x[1]["id"]))
    return {"completed": done, "expected": expected, "paused": paused, "due": due, "start": start, "end": end,
            "today": today, "fut0": fut0}


def _cat(v):
    return (v.get("category") or "").strip() or "No category"


def section(g, range_label, colours=None, heading="Completion"):
    e = html.escape
    colours = colours or {}
    dot = lambda v: f'<span class="dot" style="background:{colours.get(_cat(v), "#8a96a0")}"></span>'
    today = g["today"]

    def bar(days):
        pct = max(0, min(100, round(100 * days / REQUIRED_DAYS)))
        return (f'<span style="display:inline-block;width:70px;height:6px;border-radius:3px;background:#e3e8ee;'
                f'vertical-align:middle;margin-right:6px"><span style="display:block;width:{pct}%;height:100%;'
                f'border-radius:3px;background:#0b4f7a"></span></span>{pct}%')

    rows_c = [(v, f'<tr><td>{dot(v)}<b>{e(v["id"])}</b></td><td>{e(v["vessel_name"])}</td><td>{e(_cat(v))}</td>'
                     f'<td>{d:%d %b %Y}</td></tr>') for d, v in g["completed"]]
    rows_e = [(v, f'<tr><td>{dot(v)}<b>{e(v["id"])}</b></td><td>{e(v["vessel_name"])}</td><td>{e(_cat(v))}</td>'
                     f'<td class=num>{days}</td><td class=num>{max(0, (d - today).days)}</td><td>{d:%d %b %Y}</td>'
                     f'<td>{bar(days)}</td></tr>') for d, v, days in g["expected"]]
    def paused_row(v, p):
        off = f'{p["paused_since"]:%d %b %Y}' if p.get("paused_since") else ""
        nxt = (f'{p["next_start"]:%d %b %Y} (exp. {p["expected_end"]:%d %b %Y})'
               if p.get("next_start") and p.get("expected_end") else '<span class="sub">not set</span>')
        return (f'<tr><td>{dot(v)}<b>{e(v["id"])}</b></td><td>{e(v["vessel_name"])}</td><td>{e(_cat(v))}</td>'
                f'<td class=num>{p["days"]}</td><td>{off}</td><td>{nxt}</td></tr>')
    rows_p = [(v, paused_row(v, p)) for v, p in g["paused"]]

    def note(p):
        if p["status"] == "onboard":
            return ""
        return ("after resume " if p["days"] > 0 else "starts ") + f'{p["next_start"]:%d %b %Y}'
    rows_d = [(v, f'<tr><td>{dot(v)}<b>{e(v["id"])}</b></td><td>{e(v["vessel_name"])}</td><td>{e(_cat(v))}</td>'
                     f'<td class=num>{p["days"]}</td><td>{d:%d %b %Y}</td><td>{e(note(p))}</td></tr>') for d, v, p in g["due"]]
    future = g["end"] > today
    fut_label = f'{g["fut0"]:%d %b %Y} – {g["end"]:%d %b %Y}'

    def bycat(items, head):
        cols = head.count("<th")
        order = []
        for v, _ in items:
            if _cat(v) not in order:
                order.append(_cat(v))
        order.sort(key=lambda c: (c == "No category", "TS" in c.split(), c))
        out = ""
        for c in order:
            its = [h for v, h in items if _cat(v) == c]
            out += (f'<tr><td colspan="{cols}" style="font-weight:700;padding-top:8px;border-bottom:1px solid #d5dde5">'
                    f'<span class="dot" style="background:{colours.get(c, "#8a96a0")}"></span>{e(c)} '
                    f'<span class="sub">· {len(its)}</span></td></tr>' + "".join(its))
        return out

    def grp(title, n, head, rows, empty, open_=True):
        rows = bycat(rows, head) if rows else ""
        body = (f'<div class="tablewrap" style="padding:0 0 8px 18px"><table class="small" style="min-width:0;white-space:nowrap"><thead><tr>{head}'
                f'</tr></thead><tbody>{rows}</tbody></table></div>') if rows else f'<p class="sub" style="margin:4px 0 10px 18px">{empty}</p>'
        return f'<details class="grp"{" open" if open_ else ""}><summary><b>{title}</b> <span class="sub">· {n}</span></summary>{body}</details>'

    n_c, n_e, n_p, n_d = len(g["completed"]), len(g["expected"]), len(g["paused"]), len(g["due"])
    past = g["start"] <= today
    done_label = f'{g["start"]:%d %b %Y} – today' if future else range_label
    return (f'<section><h2>{e(heading)}</h2>'
            f'<p>' + (f'<b>{n_c}</b> completed in {e(done_label)} · ' if past else '')
            + (f'<b>{n_d}</b> expected to complete {e(fut_label)} · ' if future else '')
            + f'<b>{n_e}</b> on board · <b>{n_p}</b> paused.</p>'
            + (grp(f"Completed in {e(done_label)}", n_c, "<th>Code</th><th>Vessel</th><th>Category</th><th>Completed on</th>",
                   rows_c, "None in this period.") if past else '')
            + (grp(f"Expected to complete {e(fut_label)}", n_d,
                   "<th>Code</th><th>Vessel</th><th>Category</th><th class=num>Days so far</th><th>Expected</th><th>Note</th>",
                   rows_d, "None expected in this range.") if future else '')
            + grp("Expected completion (still on board, soonest first)", n_e,
                  "<th>Code</th><th>Vessel</th><th>Category</th><th class=num>Days on board</th><th class=num>Days left</th>"
                  "<th>Expected</th><th>Progress</th>", rows_e, "No codes on board.", open_=not future)
            + grp("Paused", n_p,
                  "<th>Code</th><th>Vessel</th><th>Category</th><th class=num>Days so far</th><th>Paused since</th><th>Resumes</th>",
                  rows_p, "None.", open_=bool(n_p))
            + '</section>')


def sheet(g):
    rows, due = [], {v["id"] for _, v, _ in g["due"]}
    for d, v in g["completed"]:
        rows.append([v["id"], v["vessel_name"], _cat(v), "Completed", REQUIRED_DAYS, 0, f"{d:%Y-%m-%d}", "", "", ""])
    for d, v, days in g["expected"]:
        rows.append([v["id"], v["vessel_name"], _cat(v), "On board", days, max(0, (d - g["today"]).days), f"{d:%Y-%m-%d}", "", "",
                     "Yes" if v["id"] in due else ""])
    for v, p in g["paused"]:
        rows.append([v["id"], v["vessel_name"], _cat(v), "Paused", p["days"], REQUIRED_DAYS - p["days"],
                     f"{p['expected_end']:%Y-%m-%d}" if p.get("expected_end") else "",
                     f"{p['paused_since']:%Y-%m-%d}" if p.get("paused_since") else "",
                     f"{p['next_start']:%Y-%m-%d}" if p.get("next_start") else "", "Yes" if v["id"] in due else ""])
    return ("Completion", HEADER, rows)


def summary_lines(g, range_label):
    soon = [x for x in g["expected"] if (x[0] - g["today"]).days <= 30]
    extra = (f"{len(g['due'])} expected to complete {g['fut0']:%d %b %Y} – {g['end']:%d %b %Y}; "
             if g["end"] > g["today"] else "")
    done_label = f"{g['start']:%d %b %Y} – today" if g["end"] > g["today"] else range_label
    return [f"Completion: {len(g['completed'])} completed in {done_label}; " + extra +
            f"{len(g['expected'])} on board ({len(soon)} expected to complete in the next 30 days); "
            f"{len(g['paused'])} paused."]
