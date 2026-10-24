"""Passcode lock for the tracker's data and reports.

The project is public, so everything sensitive is stored encrypted under vault/
and only readable with the passcode (GitHub secret REPORT_PASSCODE). The
dashboard asks for the same passcode and decrypts in the browser.

  python scripts/vault.py open    decrypt vault/ into the normal data/ and reports/ files
  python scripts/vault.py seal    encrypt changed files back into vault/ and untrack the readable copies
  python scripts/vault.py rekey   change passcode (env REPORT_PASSCODE = old, REPORT_PASSCODE_NEW = new)

Format (shared with index.html):
  vault/key.json   {"v":1, "kdf":"PBKDF2-SHA256", "iter":N, "salt":b64, "check":record}
  vault/<path>.enc one record per line; the file's text is the records' plaintexts joined.
  record           base64(12-byte nonce + AES-256-GCM ciphertext and tag)
data/positions.csv only ever grows, so each run appends one small record instead of
rewriting the file (keeps the project history small).

If REPORT_PASSCODE is not set and there is no vault yet, nothing is locked (plain mode).
"""
import base64
import glob
import hashlib
import json
import os
import subprocess
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = os.path.join(ROOT, "vault")
KEY_FILE = os.path.join(VAULT, "key.json")
CHECK_TEXT = "vessel-tracker-vault-ok"
ITERATIONS = 600_000
APPEND_ONLY = {"data/positions.csv"}


def protected_paths():
    """Relative paths of the readable files that must never be published."""
    fixed = ["data/positions.csv", "data/latest.json", "data/run_log.json", "reports/index.json"]
    found = [os.path.relpath(p, ROOT).replace(os.sep, "/")
             for pat in ("reports/*.html", "reports/*.md") for p in glob.glob(os.path.join(ROOT, pat))]
    return sorted(set(fixed + found))


def fail(msg):
    """Stop with a message that also shows as an annotation on the Actions run page."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error::{msg}")
    sys.exit(msg)


def derive(passcode, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, iterations, dklen=32)


def enc_record(key, text):
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)).decode("ascii")


def dec_record(key, record):
    raw = base64.b64decode(record)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode("utf-8")


def enc_path(rel):
    return os.path.join(VAULT, rel + ".enc")


def read_enc(key, rel):
    path = enc_path(rel)
    if not os.path.exists(path):
        return None
    with open(path, encoding="ascii") as f:
        return "".join(dec_record(key, line.strip()) for line in f if line.strip())


def write_plain(rel, text):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def read_plain(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def load_key(passcode):
    with open(KEY_FILE, encoding="utf-8") as f:
        meta = json.load(f)
    key = derive(passcode, base64.b64decode(meta["salt"]), meta["iter"])
    try:
        ok = dec_record(key, meta["check"]) == CHECK_TEXT
    except Exception:
        ok = False
    if not ok:
        fail("Vault: REPORT_PASSCODE does not match the passcode the data was locked with. Nothing changed.")
    return key


def new_key(passcode):
    salt = os.urandom(16)
    key = derive(passcode, salt, ITERATIONS)
    os.makedirs(VAULT, exist_ok=True)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS,
                   "salt": base64.b64encode(salt).decode("ascii"),
                   "check": enc_record(key, CHECK_TEXT)}, f, indent=1)
        f.write("\n")
    return key


def vault_files():
    return sorted(os.path.relpath(p, VAULT).replace(os.sep, "/")[:-4]
                  for p in glob.glob(os.path.join(VAULT, "**", "*.enc"), recursive=True))


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_open(passcode):
    if not os.path.exists(KEY_FILE):
        print("Vault: not locked yet; using the readable files.")
        return 0
    if not passcode:
        fail("Vault: data is locked but the REPORT_PASSCODE secret is missing. Nothing changed.")
    key = load_key(passcode)
    files = vault_files()
    for rel in files:
        write_plain(rel, read_enc(key, rel))
    print(f"Vault: unlocked {len(files)} file(s) for this run.")
    return 0


def cmd_seal(passcode, compact=False):
    paths = protected_paths()
    if passcode and not os.path.exists(KEY_FILE) and len(passcode) < 12:
        # Too short to lock with: keep saving readable data (so no positions are lost) until it is fixed.
        if os.environ.get("GITHUB_ACTIONS"):
            print("::warning::Data NOT locked: REPORT_PASSCODE must be at least 12 characters. Update the secret.")
        passcode = ""
    if not passcode:
        if os.path.exists(KEY_FILE):
            fail("Vault: data is locked but the REPORT_PASSCODE secret is missing. Nothing saved.")
        # Plain mode: keep committing the readable files as before.
        existing = [p for p in paths if os.path.exists(os.path.join(ROOT, p))]
        if existing:
            git("add", "-f", "--", *existing)
        print("Vault: REPORT_PASSCODE not set, so data is NOT locked yet.")
        return 0
    key = load_key(passcode) if os.path.exists(KEY_FILE) else new_key(passcode)
    changed = 0
    for rel in paths:
        text = read_plain(rel)
        if text is None:
            continue
        old = read_enc(key, rel)
        if old == text and not (compact and rel in APPEND_ONLY):
            continue
        os.makedirs(os.path.dirname(enc_path(rel)), exist_ok=True)
        if rel in APPEND_ONLY and old is not None and text.startswith(old) and not compact:
            with open(enc_path(rel), "a", encoding="ascii") as f:
                f.write(enc_record(key, text[len(old):]) + "\n")
        else:
            with open(enc_path(rel), "w", encoding="ascii") as f:
                f.write(enc_record(key, text) + "\n")
        changed += 1
    git("rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", *paths)
    print(f"Vault: locked; {changed} file(s) updated.")
    return 0


def cmd_rekey(old, new):
    if not (old and new):
        fail("Vault: set both REPORT_PASSCODE (current) and REPORT_PASSCODE_NEW (new).")
    if len(new) < 12:
        fail("Vault: the new passcode must be at least 12 characters.")
    okey = load_key(old)
    texts = {rel: read_enc(okey, rel) for rel in vault_files()}
    nkey = new_key(new)
    for rel, text in texts.items():
        with open(enc_path(rel), "w", encoding="ascii") as f:
            f.write(enc_record(nkey, text) + "\n")
    print(f"Vault: re-locked {len(texts)} file(s) with the new passcode.")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    passcode = os.environ.get("REPORT_PASSCODE", "").strip()
    if cmd == "open":
        return cmd_open(passcode)
    if cmd == "seal":
        return cmd_seal(passcode, compact=os.environ.get("VAULT_COMPACT") == "1")
    if cmd == "rekey":
        return cmd_rekey(passcode, os.environ.get("REPORT_PASSCODE_NEW", "").strip())
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
