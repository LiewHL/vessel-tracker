"""Build assets/locode.json from the UN/LOCODE code list (UNECE, public domain via datasets/un-locode).

  python scripts/build_locode.py code-list.csv country-codes.csv

Keeps locations that are ports (function digit 1), e.g. "CNYSA": "Yangshan, China".
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    codes, countries = sys.argv[1], sys.argv[2]
    names = {}
    with open(countries, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            names[(r.get("CountryCode") or r.get("Code") or "").strip()] = (r.get("CountryName") or r.get("Name") or "").strip().title()
    fix = {"Korea, Republic Of": "South Korea", "Taiwan, Province Of China": "Taiwan", "Viet Nam": "Vietnam",
           "Russian Federation": "Russia", "Iran, Islamic Republic Of": "Iran", "United States Of America": "United States",
           "United Kingdom Of Great Britain And Northern Ireland": "United Kingdom", "Netherlands (Kingdom Of The)": "Netherlands",
           "Türkiye": "Turkey", "Hong Kong": "Hong Kong", "Korea (Republic Of)": "South Korea"}
    names = {k: fix.get(v, v) for k, v in names.items()}
    out = {}
    with open(codes, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cc, loc = (r.get("Country") or "").strip(), (r.get("Location") or "").strip()
            func = (r.get("Function") or "").strip()
            if len(cc) != 2 or len(loc) != 3 or not func.startswith("1"):
                continue
            name = (r.get("NameWoDiacritics") or r.get("Name") or "").strip()
            country = names.get(cc, cc)
            out[cc + loc] = f"{name}, {country}" if country and country.lower() != name.lower() else name
    with open(os.path.join(ROOT, "assets", "locode.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "UN/LOCODE (UNECE), ports only", "codes": dict(sorted(out.items()))}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} port codes written.")


if __name__ == "__main__":
    main()
