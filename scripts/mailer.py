import imaplib
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import make_msgid


def _env(name, default=""):
    return os.environ.get(name, "").strip() or default


def staff_address(slot):
    for line in re.split(r"[\n;,]", os.environ.get("STAFF_EMAILS", "")):
        k, _, v = line.partition("=")
        if k.strip().upper() == slot.upper() and v.strip():
            return v.strip()
    return ""


def recipients(slot=None):
    domain = _env("EMAIL_DOMAIN", "sp.edu.sg").lower().lstrip("@")
    slot = slot if slot is not None else _env("SEND_TO")
    if slot:
        a = staff_address(slot)
        all_to = [a] if a else []
    else:
        all_to = [a.strip() for a in re.split(r"[;,]", os.environ.get("EMAIL_TO", "")) if a.strip()]
    ok = [a for a in all_to if a.lower().endswith("@" + domain)]
    return ok, len(all_to) - len(ok)


def _warn(text):
    print(("::warning::" if os.environ.get("GITHUB_ACTIONS") else "") + text)


def send(subject, body, attachments=(), send_to=None):
    slot = send_to if send_to is not None else _env("SEND_TO")
    to, skipped = recipients(slot)
    user, password = _env("SMTP_USER"), _env("SMTP_PASS")
    if skipped:
        _warn(f"{skipped} recipient address(es) skipped: only @{_env('EMAIL_DOMAIN', 'sp.edu.sg')} addresses are sent to.")
    if slot and not to and not skipped:
        _warn(f"No address for {slot} in the STAFF_EMAILS secret, so no email was sent.")
        return 3
    if not (user and password and (os.environ.get("EMAIL_TO", "").strip() or slot)):
        print("Email not configured (EMAIL_TO / SMTP_USER / SMTP_PASS secrets missing).")
        return 3
    if not to:
        _warn("No allowed recipients, so no email was sent.")
        return 3
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Vessel Tracking <{user}>"
    msg["To"] = "undisclosed-recipients:;"
    msg["Message-ID"] = make_msgid(domain="vessel-tracker.local")
    msg.set_content(body)
    for data, main, sub, name in attachments:
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    try:
        with smtplib.SMTP(_env("SMTP_HOST", "smtp.gmail.com"), int(_env("SMTP_PORT", "587")), timeout=60) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, password)
            s.send_message(msg, from_addr=user, to_addrs=to)
    except Exception as exc:
        print(f"Email failed: {type(exc).__name__}")
        return 1
    print(f"Email sent to {len(to)} recipient(s).")
    remove_sent_copy(user, password, msg["Message-ID"])
    return 0


def _folder(imap, flag):
    typ, rows = imap.list()
    for raw in rows or []:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if flag.lower() in line.lower():
            m = re.search(r'"([^"]*)"\s*$', line) or re.search(r"(\S+)\s*$", line)
            if m:
                return m.group(1)
    return None


def _find(imap, msgid, tries=1):
    for i in range(tries):
        typ, data = imap.uid("SEARCH", None, "HEADER", "Message-ID", f'"{msgid}"')
        ids = (data[0] or b"").split() if typ == "OK" and data else []
        if ids:
            return ids
        time.sleep(5)
    return []


def remove_sent_copy(user, password, msgid):
    try:
        with imaplib.IMAP4_SSL(_env("IMAP_HOST", "imap.gmail.com"), timeout=60) as imap:
            imap.login(user, password)
            sent, trash = _folder(imap, "\\Sent"), _folder(imap, "\\Trash")
            if not (sent and trash):
                _warn("Sent copy not removed: could not find the Sent / Trash folders.")
                return
            imap.select(f'"{sent}"')
            ids = _find(imap, msgid, tries=8)
            if not ids:
                _warn("Sent copy not removed: it was not found in Sent.")
                return
            for uid in ids:
                imap.uid("MOVE", uid, f'"{trash}"')
            imap.select(f'"{trash}"')
            for uid in _find(imap, msgid, tries=4):
                imap.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
            imap.expunge()
            print("Sent copy removed from the sending account.")
    except Exception as exc:
        _warn(f"Sent copy not removed ({type(exc).__name__}). The email itself was sent.")
