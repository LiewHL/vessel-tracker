import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT

PATH = os.path.join(ROOT, "data", "send.json")


def main():
    key = os.environ.get("SEND_KEY", "").strip()
    if not key:
        return 0
    if key.lower() == "off":
        data = {}
    else:
        old = None
        if os.path.exists(PATH):
            with open(PATH, encoding="utf-8") as f:
                old = f.read()
        prev = json.loads(old).get("repo", "") if old else ""
        repo = os.environ.get("SEND_REPO", "").strip() or prev
        data = {"key": key, "repo": repo}
    old = None
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as f:
            old = f.read()
    new = json.dumps(data)
    if new != old:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(new)
        print("Send button key updated (kept locked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
