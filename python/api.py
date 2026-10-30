"""Bounded HTTP attempts and safe errors using Python's standard library.

Only a rate-limited GET can be replayed here. Mutations and token exchanges stay
single-attempt because a lost response does not prove that a write failed.
"""

import http.client
import json
import math
import os
import queue
import random
import re
import socket
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit


class ExampleError(Exception):
    """An actionable, deliberately sanitized error suitable for console output."""


def origin(value):
    """Accept an HTTPS origin, allowing plain HTTP only for loopback fixtures."""
    try:
        url = urlsplit(value)
        _ = url.port  # Validate malformed ports before constructing a connection.
        local = url.hostname in {'localhost', '127.0.0.1', '::1'}
        if (
            url.scheme not in {'https', 'http'}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {'', '/'}
            or (url.scheme == 'http' and not local)
            or any(ord(character) < 33 for character in value)
        ):
            raise ValueError
    except ValueError:
        raise ExampleError(
            'Use a canonical HTTPS origin; HTTP is allowed only on literal loopback.'
        ) from None
    return url.scheme + '://' + url.netloc


def required(value, description):
    """Require nonempty text before trusting an ID, revision or secret."""
    if not isinstance(value, str) or not value:
        raise ExampleError(
            f'Missing {description}. Keep private evidence and reconcile before another write.'
        )
    return value


def safe(value):
    """Allow only bounded identifiers in logs, never arbitrary response content."""
    if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        return value
    return None


def retry_delay(header, attempt, now=None):
    """Retry-After is a minimum. Refuse waits outside this example's budget."""
    now = time.time() if now is None else now
    wait = 2 ** attempt
    if header:
        header = header.strip()
        if re.fullmatch(r'[0-9]+', header):
            # Bound decimal text before conversion: huge values must not overflow
            # or fall through to a shorter fallback wait. Leading zeroes are valid.
            decimal = header.lstrip('0') or '0'
            if len(decimal) > 1 or decimal > '5':
                return None
            wait = int(decimal)
        else:
            try:
                wait = max(0, parsedate_to_datetime(header).timestamp() - now)
            except (ValueError, TypeError, OverflowError):
                pass
    if not math.isfinite(wait) or wait > 5:
        return None
    return min(5, wait + random.uniform(0.02, 0.1))


def send(method, url, headers, body=None, timeout=15):
    """One attempt, bounded across connection, headers and body; no redirect handling."""
    target = urlsplit(url)
    connection_type = (
        http.client.HTTPSConnection if target.scheme == 'https' else http.client.HTTPConnection
    )
    connection = connection_type(target.hostname, target.port, timeout=timeout)
    cancelled = threading.Event()
    results = queue.Queue(maxsize=1)

    def work():
        try:
            connection.connect()
            # A timeout closes this socket. Never let request() reopen it after
            # the cancellation check and send an abandoned mutation late.
            connection.auto_open = False
            # A DNS/connect completion after the deadline must not send a late mutation.
            if cancelled.is_set():
                return
            path = target.path + ('?' + target.query if target.query else '')
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(20 * 1024 * 1024 + 1)
            if len(raw) > 20 * 1024 * 1024:
                raise ExampleError('Response exceeds the example limit; no partial export was saved.')
            results.put((response.status, dict(response.getheaders()), raw))
        except Exception as error:
            results.put(error)
        finally:
            connection.close()

    # The daemon worker gives DNS and complete-body reads the same finite deadline.
    # This is one attempt, not an automatic replay of an uncertain mutation.
    threading.Thread(target=work, daemon=True).start()
    try:
        result = results.get(timeout=timeout)
    except queue.Empty:
        cancelled.set()
        if connection.sock is not None:
            try:
                connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()
        result = TimeoutError()
    if isinstance(result, Exception):
        if isinstance(result, ExampleError):
            raise result
        if method == 'GET':
            raise ExampleError(
                'Read failed, timed out or was cancelled. Retry deliberately; '
                'no network retry was attempted.'
            ) from None
        raise ExampleError(
            'Write response unavailable or timed out; outcome uncertain. '
            'Keep input and reconcile before another mutation.'
        ) from None
    return result


def failure(status, headers, body):
    """Describe a refused request without copying its potentially private body."""
    guidance = {
        401: 'Authentication refused. Reconnect or replace revoked authorization; do not retry blindly.',
        409: 'Conflict. Keep input and compare current content; never silently refresh the revision guard.',
        423: (
            'Content is temporarily read-only. Keep input; wait for conversion, '
            'review current state, then deliberately retry.'
        ),
        429: 'Rate limited. Pause; mutations are single-attempt and are not automatically replayed.',
    }.get(status, 'Request refused. Review the canonical origin, permissions, plan and configuration.')
    detail = body.get('details') if isinstance(body.get('details'), dict) else {}
    values = [
        safe(body.get('code')),
        safe(detail.get('reason')),
        safe(headers.get('x-request-id')) or safe(body.get('requestId')),
    ]
    identifiers = ' '.join(value for value in values if value)
    return ExampleError(f'HTTP {status} {identifiers}. {guidance}')


class Api:
    """Hold one server-side token and call the routes used by the six tasks."""

    def __init__(self):
        """Use injected authorization or exchange this application's credentials once."""
        self.base = origin(os.environ.get('MDLOGIC_API_ORIGIN', 'https://api.markdownlogic.com'))
        self.token = os.environ.get('MDLOGIC_TOKEN')
        if self.token:
            return
        issuer = origin(os.environ.get('MDLOGIC_OAUTH_ISSUER', 'https://auth.markdownlogic.com'))
        credentials = {
            'grant_type': 'client_credentials',
            'client_id': required(os.environ.get('MDLOGIC_CLIENT_ID'), 'MDLOGIC_CLIENT_ID'),
            'client_secret': required(
                os.environ.get('MDLOGIC_CLIENT_SECRET'), 'MDLOGIC_CLIENT_SECRET'
            ),
            'scope': 'projects:read documents:read documents:write',
        }
        form = urlencode(credentials).encode()
        status, _, raw = send(
            'POST',
            issuer + '/oauth/token',
            {'Content-Type': 'application/x-www-form-urlencoded'},
            form,
        )
        try:
            data = json.loads(raw)
            self.token = data['access_token'] if isinstance(data, dict) else None
        except (ValueError, KeyError):
            self.token = None
        if not 200 <= status < 300 or not isinstance(self.token, str) or not self.token:
            raise ExampleError(
                'Token exchange refused. Check the authorized credential and scopes; '
                'reconnect if revoked.'
            )

    def request(self, method, path, body=None, binary=False):
        """Return an object (or export bytes), retrying only GET responses with 429.

        Every attempt includes the complete response body in its deadline.
        Network failures, redirects and writes are never automatically replayed.
        """
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers = {'Authorization': 'Bearer ' + self.token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        for attempt in range(3):
            status, response_headers, raw = send(method, self.base + path, headers, encoded)
            response_headers = {key.lower(): value for key, value in response_headers.items()}
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    data = {}
            except ValueError:
                data = {}
            if 200 <= status < 300:
                return raw if binary else data
            error = failure(status, response_headers, data)
            if method != 'GET' or status != 429 or attempt == 2:
                raise error
            delay = retry_delay(response_headers.get('retry-after'), attempt)
            if delay is None:
                raise error
            time.sleep(delay)
