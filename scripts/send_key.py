"""Put the dashboard's Send button key into the locked data (data/send.json, sealed into vault/).

Reads the SEND_KEY secret (a GitHub token that can only start the "Send report" job in the small
private request repo) and optional SEND_REPO (default <owner>/vessel-tracker-requests). The key is
never stored readable: vault.py seal encrypts data/send.json with the passcode. If SEND_KEY is not
set, nothing changes; set SEND_KEY to "off" to remove the Send button.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT  # noqa: E402

PATH = os.path.join(ROOT, "data", "send.json")


def main():
    key = os.environ.get("SEND_KEY", "").strip()
    if not key:
        return 0
    if key.lower() == "off":
        data = {}
    else:
        owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
        repo = os.environ.get("SEND_REPO", "").strip() or (f"{owner}/vessel-tracker-requests" if owner else "")
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
