"""Verify current UIS credentials without processing courses or sending mail."""

import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.webvpn import WebVPNSession
from src.runtime import config


def verify_login(max_attempts=5):
    for attempt in range(max_attempts):
        try:
            vpn = WebVPNSession()
            vpn.login()
            vpn.authenticate_icourse()
            print("Current UIS credentials verified for WebVPN and iCourse.")
            return
        except (RuntimeError, requests.RequestException) as exc:
            # An explicit credential rejection needs user action, not retries.
            if ("Authentication failed (code=" in str(exc)
                    or attempt + 1 == max_attempts):
                raise
            # WebVPN can accept credentials but return a cold session. Use a
            # fresh session on transient transport/CAS failures, as main does.
            print(f"Session not ready; retrying login ({attempt + 2}/{max_attempts}).")
            time.sleep(5)


def main():
    if not config.STUDENT_ID or not config.PASSWORD:
        raise ValueError("STUID and UISPSW secrets are required")
    verify_login()


if __name__ == "__main__":
    main()
