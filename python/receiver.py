"""Authenticate deliveries and durably accept them into a small local inbox."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
import time

from api import ExampleError, required


def verify_signature(header, raw, secret, now=None):
    now = int(time.time()) if now is None else now
    fields = [part.strip() for part in (header or '').split(',')]
    timestamp = next((part[2:] for part in fields if part.startswith('t=')), '')
    if not re.fullmatch(r'[0-9]{1,20}', timestamp):
        return False
    timestamp = int(timestamp)
    if timestamp <= 0 or abs(now - timestamp) > 300:
        return False
    expected = hmac.new(secret.encode(), str(timestamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(part[3:], expected) for part in fields if re.fullmatch(r'v1=[0-9a-f]{64}', part))


def receive(directory):
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
            pass  # Never log event envelopes, actor email or signatures.

        def reply(self, status):
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_POST(self):
            if self.path != '/webhook':
                return self.reply(404)
            self.connection.settimeout(10)
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if length < 0:
                    return self.reply(400)
                if length > 1024 * 1024:
                    return self.reply(413)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    return self.reply(400)
                if not verify_signature(self.headers.get('MDL-Signature'), raw, secret):
                    return self.reply(401)
                try:
                    event = json.loads(raw)
                except ValueError:
                    return self.reply(400)
                if (not isinstance(event, dict) or not isinstance(event.get('id'), str) or not event['id']
                        or not isinstance(event.get('type'), str) or not event['type']
                        or event['id'] != self.headers.get('MDL-Event-Id')
                        or (self.headers.get('MDL-Event-Type') is not None and event['type'] != self.headers['MDL-Event-Type'])):
                    return self.reply(400)
                target = inbox / (hashlib.sha256(event['id'].encode()).hexdigest() + '.json')
                # The complete authenticated file is the work item, not a processed flag.
                # Production systems should transactionally deduplicate and enqueue a job.
                with tempfile.NamedTemporaryFile(dir=inbox, prefix='.pending-', delete=False) as output:
                    temporary = Path(output.name)
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    try:
                        os.link(temporary, target)
                    except FileExistsError:
                        return self.reply(200)
                    return self.reply(202)
                finally:
                    temporary.unlink(missing_ok=True)
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
