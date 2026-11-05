"""Get the vessel list (vessels.csv) from the private repo, so it is never public.

Reads LIST_KEY (a token that can only READ the private repo) and optional LIST_REPO (default
<owner>/vessel-tracker-requests). Writes vessels.csv for this run only; vault.py seal keeps a locked
copy for the dashboard. If the key is not set or the fetch fails, the locked copy from the last run
is used (vault.py open has already put it in place). Prints counts only.
"""
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROSTER  # noqa: E402


def warn(text):
    print(("::warning::" if os.environ.get("GITHUB_ACTIONS") else "") + text)


def main():
    key = os.environ.get("LIST_KEY", "").strip()
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
    repo = os.environ.get("LIST_REPO", "").strip() or (f"{owner}/vessel-tracker-requests" if owner else "")
    have = os.path.exists(ROSTER)
    if not key or not repo:
        print("Vessel list: using the locked copy." if have else "Vessel list: none found.")
        return 0 if have else 1
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents/vessels.csv",
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/vnd.github.raw+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if not data.strip():
            raise ValueError("empty")
    except Exception as e:
        warn(f"Vessel list could not be fetched ({getattr(e, 'code', type(e).__name__)}); using the locked copy.")
        return 0 if have else 1
    with open(ROSTER, "wb") as f:
        f.write(data)
    print(f"Vessel list: {max(0, data.decode('utf-8', 'replace').count(chr(10)) - 1)} rows from the private repo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
