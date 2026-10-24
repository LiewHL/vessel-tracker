"""Send a plain-text email to the private recipient list (GitHub secrets).

Same settings as send_email.py: EMAIL_TO, SMTP_USER, SMTP_PASS, optional SMTP_HOST / SMTP_PORT.
Recipients go in Bcc and are never printed. Returns 0 sent, 3 not configured, 1 failed.
"""
import os
import re
import smtplib
import ssl
from email.message import EmailMessage


def send(subject, body):
    to = [a.strip() for a in re.split(r"[;,]", os.environ.get("EMAIL_TO", "")) if a.strip()]
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    if not (to and user and password):
        print("Email not configured, so no alert email was sent.")
        return 3
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Vessel Tracking <{user}>"
    msg["To"] = user
    msg["Bcc"] = ", ".join(to)
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ.get("SMTP_HOST", "").strip() or "smtp.gmail.com",
                          int(os.environ.get("SMTP_PORT", "").strip() or 587), timeout=60) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, password)
            s.send_message(msg)
    except Exception as exc:  # never echo addresses or credentials
        print(f"Alert email failed: {type(exc).__name__}")
        return 1
    print(f"Alert email sent to {len(to)} recipient(s).")
    return 0
