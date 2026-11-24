import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mailer import send as _send


def send(subject, body, send_to=None):
    return _send(subject, body, send_to=send_to)
