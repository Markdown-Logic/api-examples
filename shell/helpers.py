#!/usr/bin/env python3
"""Small standard-library adapters for curl: URLs, retry delays and OAuth forms."""

import math
import os
import random
import sys
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit


def origin(value):
    """Accept HTTPS origins, with plain HTTP reserved for local test servers."""
    url = urlsplit(value)
    localhost = url.hostname in ("localhost", "127.0.0.1", "::1")
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or (url.scheme == "http" and not localhost)
    ):
        raise ValueError("Use an HTTPS origin; HTTP is allowed only for literal localhost.")

    # Accessing port also rejects nonnumeric and out-of-range port values.
    _ = url.port
    return value.rstrip("/")


def retry_delay(raw, fallback):
    """Honor Retry-After without shortening a server wait that exceeds our budget."""
    raw = raw.strip()
    if raw.isdigit():
        digits = raw.lstrip("0") or "0"
        # Bound the string before integer conversion, including enormous headers.
        if len(digits) > 1 or digits > "5":
            raise ValueError("Retry-After exceeds budget.")
        delay = int(digits)
    else:
        try:
            delay = math.ceil(parsedate_to_datetime(raw).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            delay = fallback

    delay = max(0, delay)
    if delay > 5:
        raise ValueError("Retry-After exceeds the five-second wait budget.")
    return min(5.0, delay + random.uniform(0.02, 0.10))


def client_credentials_form():
    """Encode credentials read from the environment, never command arguments."""
    return urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["MDLOGIC_CLIENT_ID"],
            "client_secret": os.environ["MDLOGIC_CLIENT_SECRET"],
            "scope": "projects:read documents:read documents:write",
        }
    )


def main():
    command = sys.argv[1]
    if command == "origin":
        print(origin(sys.argv[2]))
    elif command == "wait":
        print(retry_delay(sys.argv[2], int(sys.argv[3])))
    elif command == "input":
        # Validate bytes without normalizing CRLF or changing the source file.
        Path(sys.argv[2]).read_bytes().decode("utf-8", errors="strict")
    elif command == "form":
        print(client_credentials_form(), end="")
    else:
        raise ValueError("Unknown helper command.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError):
        # Avoid logging credentials, input content or filesystem details.
        print("Configuration, input or Retry-After exceeds the example’s allowed bounds.", file=sys.stderr)
        sys.exit(1)
