#!/usr/bin/env python3
"""Authenticate webhook bytes and queue each signed event once in a private inbox."""

import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 1024 * 1024
TIMESTAMP_TOLERANCE = 300


def verify(header, raw, secret, now=None):
    """Check MDL's timestamp + '.' + raw-body HMAC before decoding the JSON."""
    fields = [part.strip() for part in header.split(",")]
    timestamps = [part[2:] for part in fields if part.startswith("t=")]
    if len(timestamps) != 1 or not re.fullmatch(r"[0-9]{1,12}", timestamps[0]):
        return False

    timestamp = int(timestamps[0])
    current_time = int(time.time() if now is None else now)
    if timestamp <= 0 or abs(current_time - timestamp) > TIMESTAMP_TOLERANCE:
        return False

    # Parse for freshness, but authenticate the exact timestamp text sent by MDL.
    signed_bytes = timestamps[0].encode() + b"." + raw
    expected = hmac.new(secret.encode(), signed_bytes, hashlib.sha256).hexdigest()

    # Rotation can produce multiple v1 values. Accept any valid digest using a
    # constant-time comparison; never parse and reserialize the signed body.
    return any(
        re.fullmatch(r"[0-9a-f]{64}", part[3:]) is not None
        and hmac.compare_digest(part[3:], expected)
        for part in fields
        if part.startswith("v1=")
    )


def accept(inbox, event):
    """Publish a complete synced file atomically; duplicate event IDs return False."""
    key = hashlib.sha256(event["id"].encode()).hexdigest()
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=inbox)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(event, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        # Hard-link creation refuses an existing destination atomically, so a
        # concurrent duplicate cannot overwrite or read a partially written file.
        try:
            os.link(temporary, inbox / (key + ".json"))
        except FileExistsError:
            return False

        directory = os.open(inbox, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        os.unlink(temporary)


class Receiver(BaseHTTPRequestHandler):
    """Minimal local ingress: authenticate, validate identity, then persist work."""

    secret = ""
    inbox = None

    def log_message(self, *args):
        # Access logs can expose actor details or URLs; keep this receiver quiet.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def reply(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def valid_identity(self, event):
        """Require delivery headers to agree with the authenticated event body."""
        return (
            isinstance(event, dict)
            and isinstance(event.get("id"), str)
            and bool(event["id"])
            and len(event["id"].encode()) <= 512
            and isinstance(event.get("type"), str)
            and bool(event["type"])
            and event["id"] == self.headers.get("MDL-Event-Id")
            and (
                self.headers.get("MDL-Event-Type") is None
                or event["type"] == self.headers["MDL-Event-Type"]
            )
        )

    def do_POST(self):
        if self.path != "/webhook":
            self.reply(404)
            return
        if self.headers.get("Transfer-Encoding"):
            self.reply(400)
            return

        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0:
                self.reply(400)
                return
            if length > MAX_BODY:
                self.reply(413)
                return

            raw = self.rfile.read(length)
            if len(raw) != length:
                self.reply(400)
                return
            if not verify(self.headers.get("MDL-Signature", ""), raw, self.secret):
                self.reply(401)
                return

            event = json.loads(raw)
            if not self.valid_identity(event):
                self.reply(400)
                return

            # 202 acknowledges queued work, not completed business processing.
            self.reply(202 if accept(self.inbox, event) else 200)
        except (ValueError, UnicodeError):
            self.reply(400)
        except (OSError, TimeoutError):
            self.reply(503)


def main():
    os.umask(0o077)
    secret = os.environ.get("MDLOGIC_WEBHOOK_SECRET", "")
    if not secret:
        sys.exit("Set MDLOGIC_WEBHOOK_SECRET to the once-only signing secret.")

    inbox = Path(os.environ.get("MDLOGIC_STATE_DIR", ".local/shell")) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    inbox.chmod(0o700)
    inbox.parent.chmod(0o700)
    Receiver.secret = secret
    Receiver.inbox = inbox

    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        sys.exit("PORT must be 1..65535.")
    bind = os.environ.get("MDLOGIC_WEBHOOK_BIND", "127.0.0.1")
    if bind not in ("127.0.0.1", "0.0.0.0"):
        sys.exit("Invalid webhook bind address.")

    server = ThreadingHTTPServer((bind, port), Receiver)
    print(f"Webhook inbox listening on http://127.0.0.1:{port}/webhook", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
