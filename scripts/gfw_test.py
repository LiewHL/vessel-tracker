import json, os, sys, urllib.parse, urllib.request
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import roster_rows

API = "https://gateway.api.globalfishingwatch.org/v3"
TOK = os.environ.get("GFW_TOKEN", "")


def call(path, params=None, body=None):
    url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json", "User-Agent": "voyage-monitor/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode("utf-8", "replace"))
            msg = j.get("error") or j.get("message") or j.get("messages") or ""
        except Exception:
            msg = ""
        return f"{e.code}:{str(msg)[:80]}", {}
    except Exception as e:
        return type(e).__name__, {}


def main():
    if not TOK:
        print("GFW test: token missing."); return 1
    today = date.today()
    rows = [r for r in roster_rows() if r.get("mmsi", "").strip().isdigit() and r.get("start_date")
            and r["start_date"] <= today.isoformat()]
    mmsis = sorted({r["mmsi"].strip() for r in rows})
    start, end = (today - timedelta(days=60)).isoformat(), today.isoformat()
    found, visits, pres, last_pres, last_visit, codes, keys_e, keys_p = 0, 0, 0, "", "", set(), [], []
    for m in mmsis:
        st, d = call("/vessels/search", {"query": m, "datasets[0]": "public-global-vessel-identity:latest"})
        codes.add(f"search {st}")
        ids = []
        for e in (d.get("entries") or []):
            for s in (e.get("selfReportedInfo") or []):
                if str(s.get("ssvid")) == m and s.get("id"):
                    ids.append(s["id"])
        if not ids:
            continue
        found += 1
        for ds in ("public-global-port-visits-events:latest", "public-global-gaps-events:latest"):
            st, d = call("/events", {"datasets[0]": ds, **{f"vessels[{i}]": v for i, v in enumerate(ids)}, "start-date": start, "end-date": end,
                                     "limit": 100, "offset": 0})
            codes.add(f"events[{ds.split(':')[0][-22:]}] {st}")
            if st == 200:
                ent = d.get("entries") or []
                visits += len(ent)
                for x in ent:
                    last_visit = max(last_visit, (x.get("end") or x.get("start") or "")[:10])
                if ent and not keys_e:
                    keys_e = sorted(ent[0].keys()) + sorted((ent[0].get("port_visit") or {}).keys())
        flt = "vessel_id in (" + ",".join(f"'{i}'" for i in ids) + ")"
        st, d = call("/4wings/report", {"spatial-resolution": "HIGH", "temporal-resolution": "HOURLY", "group-by": "VESSEL_ID",
                                        "datasets[0]": "public-global-presence:latest", "filters[0]": flt,
                                        "date-range": f"{start},{end}", "format": "JSON", "spatial-aggregation": "false"},
                     body={"geojson": {"type": "Polygon", "coordinates": [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]]}})
        codes.add(f"presence {st}")
        if st == 200:
            for blk in (d.get("entries") or []):
                for _, rs in (blk.items() if isinstance(blk, dict) else []):
                    for r in rs or []:
                        pres += 1
                        last_pres = max(last_pres, str(r.get("date", ""))[:13])
                        if not keys_p:
                            keys_p = sorted(r.keys())
    print(f"GFW test: {len(mmsis)} ship(s) checked, {found} found; port visits (60 d): {visits}, latest {last_visit or '-'}; "
          f"hourly positions (60 d): {pres}, latest {last_pres or '-'}.")
    print("Responses:", ", ".join(sorted(codes)))
    print("Event fields:", ", ".join(keys_e) or "-")
    print("Position fields:", ", ".join(keys_p) or "-")
    return 0


if __name__ == "__main__":
    sys.exit(main())
