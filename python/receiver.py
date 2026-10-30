"""Authenticate deliveries and durably accept them into a small local inbox."""

import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from api import ExampleError, required

MAX_DELIVERY_BYTES = 1024 * 1024
SIGNATURE_TOLERANCE_SECONDS = 300


def verify_signature(header, raw, secret, now=None):
    """Verify timestamp + '.' + exact body bytes using any supplied v1 signature.

    The timestamp bounds replay attempts. Persistent event-ID deduplication is
    still required: an authentic delivery may legitimately arrive more than once.
    """
    now = int(time.time()) if now is None else now
    fields = [part.strip() for part in (header or '').split(',')]
    timestamp_text = next((part[2:] for part in fields if part.startswith('t=')), '')
    if not re.fullmatch(r'[0-9]{1,20}', timestamp_text):
        return False
    timestamp = int(timestamp_text)
    if timestamp <= 0 or abs(now - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False

    # Parse for freshness, but authenticate the original timestamp text.
    signed_bytes = timestamp_text.encode() + b'.' + raw
    expected = hmac.new(secret.encode(), signed_bytes, hashlib.sha256).hexdigest()
    return any(
        hmac.compare_digest(part[3:], expected)
        for part in fields
        if re.fullmatch(r'v1=[0-9a-f]{64}', part)
    )


def delivery_event(raw, headers):
    """Parse an authenticated envelope and match its signed identity to headers."""
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    event_id = event.get('id')
    event_type = event.get('type')
    if not isinstance(event_id, str) or not event_id:
        return None
    if not isinstance(event_type, str) or not event_type:
        return None
    if event_id != headers.get('MDL-Event-Id'):
        return None
    header_type = headers.get('MDL-Event-Type')
    if header_type is not None and event_type != header_type:
        return None
    return event


def accept_delivery(inbox, event_id, raw):
    """Atomically publish one complete work item; return False for a duplicate.

    A hard link publishes the synced file only if its event-ID name is absent.
    This handles concurrent retries without exposing a partially written body.
    Production should transactionally deduplicate and enqueue a durable job.
    """
    filename = hashlib.sha256(event_id.encode()).hexdigest() + '.json'
    with tempfile.NamedTemporaryFile(dir=inbox, prefix='.pending-', delete=False) as output:
        temporary = Path(output.name)
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    try:
        try:
            os.link(temporary, inbox / filename)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def receive(directory):
    """Listen locally and acknowledge only authenticated, durably stored events."""
    secret = required(os.environ.get('MDLOGIC_WEBHOOK_SECRET'), 'MDLOGIC_WEBHOOK_SECRET')
    inbox = directory / 'inbox'
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    inbox.chmod(0o700)
    try:
        port = int(os.environ.get('PORT', '8080'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ExampleError('PORT must be between 1 and 65535.') from None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            # HTTP access logs could expose actor email, signatures or event data.
            pass

        def reply(self, status):
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_POST(self):
            if self.path != '/webhook':
                self.reply(404)
                return
            self.connection.settimeout(10)
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if length < 0:
                    self.reply(400)
                    return
                if length > MAX_DELIVERY_BYTES:
                    self.reply(413)
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self.reply(400)
                    return

                # Authenticate the original bytes before parsing or trusting IDs.
                if not verify_signature(self.headers.get('MDL-Signature'), raw, secret):
                    self.reply(401)
                    return
                event = delivery_event(raw, self.headers)
                if event is None:
                    self.reply(400)
                    return
                accepted = accept_delivery(inbox, event['id'], raw)
                self.reply(202 if accepted else 200)
            except (OSError, ValueError):
                self.reply(500)

    bind = os.environ.get('MDLOGIC_WEBHOOK_BIND', '127.0.0.1')
    if bind not in {'127.0.0.1', '0.0.0.0'}:
        raise ExampleError('MDLOGIC_WEBHOOK_BIND must be 127.0.0.1 or 0.0.0.0.')
    server = ThreadingHTTPServer((bind, port), Handler)
    print(json.dumps({'receiver': 'ready', 'port': port}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
