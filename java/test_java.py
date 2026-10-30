"""Localhost behavioral tests; no credentials, providers or tenant writes."""

import hashlib
import hmac
import http.client
import json
import os
import pathlib
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Handler(BaseHTTPRequestHandler):
    """Serve synthetic responses and record the requests made by each scenario."""

    calls = []
    status = 200
    retries = 0
    mode = None

    def log_message(self, *_):
        pass

    def send_json(self, status, body, headers=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        fixture = type(self)
        fixture.calls.append(('GET', self.path, None))

        if fixture.mode == 'catalogue' and self.path.endswith('/webhooks/events'):
            return self.send_json(200, {'events': None})
        if fixture.mode == 'history' and self.path.endswith('/versions?limit=20&offset=0'):
            return self.send_json(200, {'items': [17], 'hasMore': False})
        if self.path.endswith('/documents/doc-1'):
            if fixture.retries:
                fixture.retries -= 1
                return self.send_json(429, {'code': 'RATE_LIMITED'}, {'Retry-After': '0'})
            return self.send_json(200, {
                'document': {
                    'id': 'doc-1',
                    'revision': 'opaque-r1',
                    'content': '# Original',
                },
            })
        return self.send_json(404, {'code': 'NOT_FOUND'})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        type(self).calls.append(('POST', self.path, json.loads(raw)))
        # Drop the response after reading a create to simulate an uncertain outcome.
        self.close_connection = True
        self.connection.shutdown(socket.SHUT_RDWR)
        self.connection.close()

    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        fixture = type(self)
        fixture.calls.append(('PUT', self.path, body))
        if fixture.status != 200:
            codes = {
                401: 'INVALID_TOKEN',
                409: 'CONFLICT',
                423: 'CONTENT_TEMPORARILY_READ_ONLY',
                429: 'RATE_LIMITED',
            }
            return self.send_json(fixture.status, {
                'code': codes[fixture.status],
                'details': {'reason': 'document-changed', 'retryable': True},
            })
        return self.send_json(200, {
            'document': {'id': 'doc-1', 'revision': 'opaque-r2'},
            'decision': 'update',
        })


class JavaExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self.temporary.name)
        (self.state / 'state.json').write_text(json.dumps({
            'projectId': 'project-1',
            'documentId': 'doc-1',
            'revision': 'old',
        }))
        self.env = {
            **os.environ,
            'MDLOGIC_API_ORIGIN': f'http://127.0.0.1:{self.server.server_port}',
            'MDLOGIC_TOKEN': 'synthetic-token',
            'MDLOGIC_STATE_DIR': str(self.state),
        }
        Handler.calls = []
        Handler.status = 200
        Handler.retries = 0
        Handler.mode = None

    def tearDown(self):
        self.temporary.cleanup()

    def run_example(self, scenario='03'):
        """Launch the real Java command with only synthetic fixture settings."""
        return subprocess.run(
            ['bash', 'java/run.sh', scenario],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_guarded_update(self):
        result = self.run_example()
        self.assertEqual(result.returncode, 0, result.stderr)
        writes = [call for call in Handler.calls if call[0] == 'PUT']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][2]['expectedRevision'], 'opaque-r1')
        self.assertEqual(
            writes[0][2]['content'],
            (ROOT / 'fixtures/report-updated.md').read_text(),
        )
        saved = json.loads((self.state / 'state.json').read_text())
        self.assertEqual(saved['revision'], 'opaque-r2')

    def test_refused_writes_are_single_attempt_and_preserve_input(self):
        source = ROOT / 'fixtures/report-updated.md'
        content = source.read_bytes()
        for status in (401, 409, 423, 429):
            with self.subTest(status=status):
                Handler.calls = []
                Handler.status = status
                result = self.run_example()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sum(call[0] == 'PUT' for call in Handler.calls), 1)
                self.assertEqual(source.read_bytes(), content)
                saved = json.loads((self.state / 'state.json').read_text())
                self.assertEqual(saved['revision'], 'old')
                self.assertNotIn('synthetic-token', result.stderr)

    def test_get_429_retries_are_bounded(self):
        Handler.retries = 2
        result = self.run_example()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[0] == 'GET' for call in Handler.calls), 3)

        Handler.calls = []
        Handler.retries = 4
        result = self.run_example()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(Handler.calls), 3)

    def test_pending_create_retains_original_target_and_blocks_repeat(self):
        self.env['MDLOGIC_TEAM'] = 'team-original'
        cases = [
            ('01', {}, '/api/v1/teams/team-original/projects'),
            ('02', {'projectId': 'project-original'}, '/api/v1/projects/project-original/artifacts'),
        ]
        for scenario, seed, path in cases:
            with self.subTest(scenario=scenario):
                (self.state / 'state.json').write_text(json.dumps(seed))
                Handler.calls = []
                result = self.run_example(scenario)
                self.assertNotEqual(result.returncode, 0)
                marker_path = self.state / f'pending-{scenario}.json'
                marker = json.loads(marker_path.read_text())
                self.assertEqual(marker['apiOrigin'], self.env['MDLOGIC_API_ORIGIN'])
                self.assertEqual(marker['method'], 'POST')
                self.assertEqual(marker['path'], path)
                self.assertEqual(marker['body'], Handler.calls[0][2])
                self.assertNotIn('synthetic-token', json.dumps(marker))

                count = len(Handler.calls)
                self.env['MDLOGIC_TEAM'] = 'changed-team'
                result = self.run_example(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(Handler.calls), count)
                self.env['MDLOGIC_TEAM'] = 'team-original'

    def test_malformed_mapping_stops_before_http(self):
        for value in [None, [], 'not an object']:
            with self.subTest(value=value):
                (self.state / 'state.json').write_text(json.dumps(value))
                result = self.run_example()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('State file must contain a JSON object', result.stderr)
                self.assertEqual(Handler.calls, [])

    def test_malformed_catalogue_and_history_stop_followup_calls(self):
        self.env['MDLOGIC_TEAM'] = 'team-1'
        self.env['MDLOGIC_WEBHOOK_URL'] = 'https://receiver.example/webhook'
        for mode, scenario, message in [
            ('catalogue', '06', 'Malformed event catalogue'),
            ('history', '04', 'Malformed history entry'),
        ]:
            with self.subTest(mode=mode):
                Handler.mode = mode
                Handler.calls = []
                result = self.run_example(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(len(Handler.calls), 1)
                self.assertEqual(Handler.calls[0][0], 'GET')
                self.assertFalse((self.state / 'report.html').exists())
                self.assertFalse((self.state / 'pending-06.json').exists())

    def test_webhook_authentication_and_persistent_dedup(self):
        # The receiver needs its private inbox, not a valid report mapping.
        (self.state / 'state.json').write_text('null')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        receiver_env = {
            **self.env,
            'MDLOGIC_WEBHOOK_SECRET': 'whsec_synthetic',
            'PORT': str(port),
        }

        def start_receiver():
            process = subprocess.Popen(
                ['bash', 'java/run.sh', 'webhook'],
                cwd=ROOT,
                env=receiver_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        return process
                except OSError:
                    time.sleep(0.05)
            process.kill()
            _, errors = process.communicate(timeout=5)
            self.fail('Receiver did not start: ' + errors.decode())

        def stop_receiver(process):
            process.terminate()
            process.wait(timeout=5)
            process.stderr.close()

        def deliver(body, event_id, signature):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                connection.request('POST', '/webhook', body, {
                    'MDL-Signature': signature,
                    'MDL-Event-Id': event_id,
                    'MDL-Event-Type': 'document.updated',
                })
                response = connection.getresponse()
                response.read()
                return response.status
            finally:
                connection.close()

        body = b'{"id":"evt-1","type":"document.updated","data":{"object":{"id":"doc-1"}}}'
        # Freshness uses the numeric value; HMAC uses the exact header text.
        timestamp = '0' + str(int(time.time()))
        digest = hmac.new(
            b'whsec_synthetic', timestamp.encode() + b'.' + body, hashlib.sha256,
        ).hexdigest()
        signature = f't={timestamp},v1={"0" * 64},v1={digest}'

        process = start_receiver()
        try:
            self.assertEqual(deliver(body, 'evt-1', 't=1,v1=bad'), 401)
            self.assertEqual(deliver(body, 'different', signature), 400)
            self.assertEqual(deliver(body, 'evt-1', signature), 202)
            self.assertEqual(deliver(body, 'evt-1', signature), 200)
        finally:
            stop_receiver(process)

        process = start_receiver()
        try:
            self.assertEqual(deliver(body, 'evt-1', signature), 200)
        finally:
            stop_receiver(process)
        self.assertEqual(len(list((self.state / 'inbox').glob('*.json'))), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
