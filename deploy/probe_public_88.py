#!/usr/bin/env python3
"""Verify that the nursery loopback port is not reachable from the public IP."""

from __future__ import annotations

import errno
import json
import socket
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


TARGET = "38.12.21.18"
PORT = 88
TIMEOUT_SECONDS = 5.0
EXPECTED_DENIAL_ERRNOS = {
    errno.ECONNREFUSED,
    errno.ETIMEDOUT,
    errno.ENETUNREACH,
    errno.EHOSTUNREACH,
}


def probe_loopback_home() -> tuple[bool, int | None, str]:
    """Require a real, enabled ShopXO HTML page on the loopback listener."""
    request = Request(
        "http://127.0.0.1:88/",
        headers={"User-Agent": "miaomu-release-probe/1"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(131072).decode("utf-8", "ignore")
            lowered = body.lower()
            enabled_page = (
                200 <= response.status < 400
                and "<html" in lowered
                and "\u82d7\u6728" in body
                and "\u5347\u7ea7\u4e2d" not in body
            )
            return enabled_page, response.status, "content_checked"
    except (OSError, URLError):
        return False, None, "loopback_unavailable"


def main() -> int:
    if len(sys.argv) != 1:
        return 2
    loopback_ok, loopback_status, loopback_reason = probe_loopback_home()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT_SECONDS)
    try:
        sock.connect((TARGET, PORT))
    except OSError as exc:
        if exc.errno in EXPECTED_DENIAL_ERRNOS or isinstance(exc, TimeoutError):
            public_status = "expected_denied"
        else:
            public_status = "probe_error"
            print(json.dumps({
                "status": public_status,
                "target": TARGET,
                "port": PORT,
                "loopback_home": loopback_ok,
                "loopback_status": loopback_status,
                "loopback_reason": loopback_reason,
            }))
            return 2
    else:
        public_status = "unexpected_reachable"
        print(json.dumps({
            "status": public_status,
            "target": TARGET,
            "port": PORT,
            "loopback_home": loopback_ok,
            "loopback_status": loopback_status,
            "loopback_reason": loopback_reason,
        }))
        return 1
    finally:
        sock.close()

    result = {
        "status": public_status if loopback_ok else "loopback_home_failed",
        "target": TARGET,
        "port": PORT,
        "loopback_home": loopback_ok,
        "loopback_status": loopback_status,
        "loopback_reason": loopback_reason,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if public_status == "expected_denied" and loopback_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
