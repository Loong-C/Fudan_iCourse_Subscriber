"""Verify current UIS credentials without processing courses or sending mail."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.webvpn import WebVPNSession
from src.runtime import config


def main():
    if not config.STUDENT_ID or not config.PASSWORD:
        raise ValueError("STUID and UISPSW secrets are required")
    # One attempt: bad credentials should not be retried until an account locks.
    vpn = WebVPNSession()
    vpn.login()
    vpn.authenticate_icourse()
    print("Current UIS credentials verified for WebVPN and iCourse.")


if __name__ == "__main__":
    main()
