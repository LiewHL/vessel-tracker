"""Email a report privately.

Usage: python scripts/send_email.py <summary.md> <report.html> "<subject>" "<dashboard url>" "<unused>" [extra files...]

All settings come from GitHub secrets, so no address or password is ever
stored in the (public) project or printed in the public run logs:
  EMAIL_TO    recipients, separated by commas or semicolons
  SMTP_USER   sending account (e.g. a Gmail address)
  SMTP_PASS   its app password
  SMTP_HOST   optional, default smtp.gmail.com
  SMTP_PORT   optional, default 587 (STARTTLS)

Exit codes: 0 sent, 3 not configured (caller may fall back), 1 failed.
"""
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage


def main():
    summary_path, report_path, subject, dash_url, report_url = sys.argv[1:6]
    extras = [p for p in sys.argv[6:] if p and os.path.isfile(p)]
    to = [a.strip() for a in re.split(r"[;,]", os.environ.get("EMAIL_TO", "")) if a.strip()]
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    if not (to and user and password):
        print("Email not configured (EMAIL_TO / SMTP_USER / SMTP_PASS secrets missing).")
        return 3
    host = os.environ.get("SMTP_HOST", "").strip() or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT", "").strip() or 587)

    with open(summary_path, encoding="utf-8") as f:
        summary = f.read().strip()
    body = (f"{summary}\n\nDashboard (passcode needed): {dash_url}\n"
            "This and past reports are also under Reports on the dashboard.\n\n"
            "Attached: the full report (open in a browser; Print > Save as PDF for a PDF copy)"
            + (" and CSV data files for Excel: " + ", ".join(os.path.basename(p) for p in extras) if extras else "")
            + ".\n")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Vessel Tracking <{user}>"
    msg["To"] = user                      # recipients go in Bcc so they never see each other
    msg["Bcc"] = ", ".join(to)
    msg.set_content(body)
    with open(report_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="html",
                           filename=os.path.basename(report_path))
    for path in extras:
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype="text", subtype="csv", filename=os.path.basename(path))

    try:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, password)
            s.send_message(msg)
    except Exception as exc:  # never echo addresses or credentials
        print(f"Email failed: {type(exc).__name__}")
        return 1
    print(f"Email sent to {len(to)} recipient(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
