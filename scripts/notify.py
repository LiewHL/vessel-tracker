"""Send a plain-text email (alerts, checks) to the private recipient list. See mailer.py.

Returns 0 sent, 3 not configured, 1 failed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mailer import send as _send  # noqa: E402


def send(subject, body, send_to=None):
    """send_to: a staff number (S3) to email that staff member only, instead of the main list."""
    return _send(subject, body, send_to=send_to)
