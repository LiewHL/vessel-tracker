"""ACI & completion: codes that completed, or are expected to complete, in a date range (past or future), with the
ASEAN / China / India countries each visited over their whole time on board (up to the range end, or today)."""
import html
import re
from datetime import datetime, time, timedelta, timezone

import countries as ctry
from common import completion_date, period_info, staff_of

SGT = timezone(timedelta(hours=8))
HEADER = ["Code", "IF", "Vessel", "Category", "ASEAN countries", "China / HK / Macao", "India", "Any ACI", "Status", "Date"]


def _cat(v):
    return (v.get("category") or "").strip() or "No category"


def _num(c):
    m = re.search(r"\d+", c or "")
    return int(m.group()) if m else -1


def _is_ts(c):
    return bool(re.search(r"\bTS\b", c or "", re.I))


def open_category(cats):
    """The latest (highest-numbered, non-test) category: shown open, the others folded."""
    pool = [c for c in cats if c and c != "No category" and not _is_ts(c)] or [c for c in cats if c]
    return max(pool, key=_num) if pool else ""


def cat_order(cats):
    oc = open_category(cats)
    return sorted(cats, key=lambda c: (c != oc, c == "No category", _is_ts(c), -_num(c), c))


def gather(roster, fixes_by_id, start, end, today):
    """start/end/today are dates. Includes codes whose completion (actual or projected) falls in [start, end]."""
    cutoff = datetime.combine(min(end, today), time(23, 59), SGT)
    items = []
    for v in roster:
        d = completion_date(v.get("stints", []))
        if not d or not (start <= d <= end):
            continue
        p = period_info(v.get("stints", []), today)
        if d <= today:
            status = "Completed"
        elif p["status"] == "onboard":
            status = "Expected"
        else:
            status = "Expected after resume"
        calls = ctry.visits(v, fixes_by_id.get(v["id"], []), None, cutoff)
        items.append({"v": v, "date": d, "status": status, "aci": ctry.aci(calls), "so_far": d > today})
    items.sort(key=lambda x: (x["date"], x["v"]["id"]))
    return {"items": items, "start": start, "end": end, "today": today}


def counts(g):
    n = len(g["items"])
    c = {k: sum(1 for x in g["items"] if x["aci"][k]) for k in ctry.ACI_KEYS}
    done = sum(1 for x in g["items"] if x["status"] == "Completed")
    return n, done, n - done, c


def section(g, label, colours=None, heading="ACI & completion"):
    e = html.escape
    colours = colours or {}
    n, done, exp, c = counts(g)
    pct = lambda k: f'<b>{c[k]}</b> of {n}' + (f' <span class="sub">({round(100 * c[k] / n)}%)</span>' if n else "")
    cats = cat_order(list(dict.fromkeys(_cat(x["v"]) for x in g["items"])))
    oc = open_category(cats)
    groups = ""
    for cat in cats:
        its = [x for x in g["items"] if _cat(x["v"]) == cat]
        dot = f'<span class="dot" style="background:{colours.get(cat, "#8a96a0")}"></span>'
        anyn = sum(1 for x in its if x["aci"]["Any"])
        rows = ""
        for x in its:
            a, v = x["aci"], x["v"]
            sf = ' <span class="sub">so far</span>' if x["so_far"] else ""
            rows += (f'<tr><td>{dot}<b>{e(v["id"])}</b></td><td>{e(staff_of(v["id"]) or "—")}</td><td>{e(v["vessel_name"])}</td>'
                     f'<td>{e(", ".join(a["ASEAN"]) or "—")}{sf if a["ASEAN"] else ""}</td>'
                     f'<td>{e(", ".join(a["China"]) or "—")}</td><td>{"Yes" if a["India"] else "—"}</td>'
                     f'<td>{"<b>Yes</b>" if a["Any"] else "No" + sf}</td><td>{e(x["status"])}</td>'
                     f'<td>{x["date"]:%d %b %Y}</td></tr>')
        groups += (f'<details class="grp"{" open" if cat == oc else ""}><summary>{dot}<b>{e(cat)}</b> <span class="sub">· '
                   f'{len(its)} code{"s" if len(its) != 1 else ""} · any ACI {anyn} of {len(its)}</span></summary>'
                   f'<div class="tablewrap" style="padding:0 0 8px 18px"><table class="small" style="white-space:nowrap">'
                   f'<thead><tr><th>Code</th><th>IF</th><th>Vessel</th><th>ASEAN</th><th>China / HK / Macao</th><th>India</th>'
                   f'<th>Any ACI</th><th>Status</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table></div></details>')
    table = groups if n else '<p class="sub">No codes complete in this range.</p>'
    return (f'<section><h2>{e(heading)}</h2>'
            f'<p><b>{n}</b> code{"s" if n != 1 else ""} completing {e(label)}: <b>{done}</b> completed, <b>{exp}</b> expected.</p>'
            f'<table class="small" style="width:auto;margin:0 0 10px"><tbody>'
            + "".join(f'<tr><td>{e(ctry.ACI_LABEL[k])}</td><td>{pct(k)}</td></tr>' for k in ctry.ACI_KEYS)
            + f'</tbody></table>{table}<p class="sub">ACI = port calls over the whole time on board up to the end of the '
            f'range (or today, marked "so far" for codes still on board). ASEAN includes Singapore; China includes Hong Kong '
            f'and Macao; Taiwan is not counted.</p></section>')


def sheet(g):
    rows = []
    for x in g["items"]:
        a, v = x["aci"], x["v"]
        rows.append([v["id"], staff_of(v["id"]) or "", v["vessel_name"], _cat(v), ", ".join(a["ASEAN"]),
                     ", ".join(a["China"]), "Yes" if a["India"] else "", "Yes" if a["Any"] else "No",
                     x["status"] + (" (ACI so far)" if x["so_far"] else ""), f"{x['date']:%Y-%m-%d}"])
    return ("ACI & completion", HEADER, rows)


def summary_lines(g, label):
    n, done, exp, c = counts(g)
    return [f"ACI & completion {label}: {n} code(s) — {done} completed, {exp} expected.",
            "ACI over their time on board: " + "; ".join(f"{ctry.ACI_LABEL[k]} {c[k]} of {n}" for k in ctry.ACI_KEYS) + "."]
