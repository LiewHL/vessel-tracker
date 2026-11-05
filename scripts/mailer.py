"""Send email privately, and leave no copy in the sending account.

Settings come from GitHub secrets, so no address or password is stored in the (public) project
or printed in the public run logs:
  EMAIL_TO      recipients, separated by commas or semicolons
  SMTP_USER     sending account (e.g. a Gmail address)
  SMTP_PASS     its app password
  SMTP_HOST     optional, default smtp.gmail.com
  SMTP_PORT     optional, default 587 (STARTTLS)
  IMAP_HOST     optional, default imap.gmail.com (used to delete the Sent copy)
  EMAIL_DOMAIN  optional, default sp.edu.sg: only addresses at this domain are sent to
  SEND_TO       set by the Send button (e.g. "S3"): send only to that staff member, whose address is
                the "S3=..." line of the STAFF_EMAILS secret (never to EMAIL_TO)

- Recipients are passed to the mail server only (no To/Cc/Bcc header lists them), so they never
  see each other and the sending account's inbox gets no copy.
- Addresses outside EMAIL_DOMAIN are skipped; the log shows only how many.
- After sending, the copy the mail service keeps in Sent is deleted (moved to Trash, then removed
  from Trash). If that fails the email still counts as sent and a warning is printed.

send() returns 0 sent, 3 not configured / no allowed recipients, 1 failed.
"""
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
    """Address for a staff number (S1, S2, ...) from STAFF_EMAILS lines like "S3=name@sp.edu.sg"."""
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
    """attachments: [(bytes, maintype, subtype, filename)]. send_to: a staff number (S3) instead of
    the main list (default: the SEND_TO setting, if any)."""
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
    except Exception as exc:  # never echo addresses or credentials
        print(f"Email failed: {type(exc).__name__}")
        return 1
    print(f"Email sent to {len(to)} recipient(s).")
    remove_sent_copy(user, password, msg["Message-ID"])
    return 0


def _folder(imap, flag):
    """Name of the mailbox carrying a special-use flag (\\Sent, \\Trash), whatever its language."""
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
            ids = _find(imap, msgid, tries=8)          # the mail service can take a few seconds to file it
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
