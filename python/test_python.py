"""Focused local checks; the root suite exercises the complete scenario matrix."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
from pathlib import Path
import tempfile
import queue
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


class PythonExamples(unittest.TestCase):
    def test_transport_helpers_and_signature_contract(self):
        self.assertTrue((HERE / 'api.py').exists(), 'Python transport implementation is missing')
        import api
        import receiver
        self.assertEqual(api.origin('https://api.example.com/'), 'https://api.example.com')
        with self.assertRaises(api.ExampleError):
            api.origin('http://external.example.com')
        self.assertGreaterEqual(api.retry_delay('2', 0, now=1000), 2)
        self.assertIsNone(api.retry_delay('2147483648', 0, now=1000))
        raw = b'{"id":"event-1","type":"document.updated","data":{"object":{"name":"caf\xc3\xa9"}}}'
        signature = hmac.new(b'whsec_synthetic', b'1000.' + raw, hashlib.sha256).hexdigest()
        header = 't=1000,v1=' + '0' * 64 + ',v1=' + signature
        self.assertTrue(receiver.verify_signature(header, raw, 'whsec_synthetic', now=1000))
        self.assertFalse(receiver.verify_signature(header, raw + b' ', 'whsec_synthetic', now=1000))
        self.assertFalse(receiver.verify_signature(header, raw, 'whsec_synthetic', now=1301))

    def test_oversized_numeric_retry_after_is_refused(self):
        import api
        for header in ('9' * 400, '9' * 5000, '0' * 5000 + '6'):
            with self.subTest(digits=len(header)):
                self.assertIsNone(api.retry_delay(header, 0, now=1000))
        self.assertGreaterEqual(api.retry_delay('0' * 5000 + '2', 0, now=1000), 2)

    def test_timed_out_request_cannot_reconnect_and_send_late(self):
        import api
        entered, release, finished, posted = (threading.Event() for _ in range(4))
        writes, outcome = [], queue.Queue()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                writes.append(self.path)
                posted.set()
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')

        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        original = api.http.client.HTTPConnection.request

        def delayed_request(connection, *args, **kwargs):
            # Hold the real request exactly between cancellation check and network send.
            entered.set()
            release.wait(2)
            try:
                return original(connection, *args, **kwargs)
            finally:
                finished.set()

        def attempt():
            try:
                outcome.put(api.send('POST', f'http://127.0.0.1:{server.server_port}/create', {}, b'{}', timeout=0.1))
            except api.ExampleError as error:
                outcome.put(error)

        try:
            with patch.object(api.http.client.HTTPConnection, 'request', delayed_request):
                caller = threading.Thread(target=attempt)
                caller.start()
                self.assertTrue(entered.wait(1), 'request did not reach the cancellation boundary')
                self.assertIsInstance(outcome.get(timeout=1), api.ExampleError)
                self.assertEqual(writes, [], 'mutation arrived before releasing the boundary')
                release.set()
                self.assertTrue(finished.wait(1))
                posted.wait(0.2)
                caller.join(timeout=1)
                self.assertEqual(writes, [], 'timed-out request reconnected and sent a late mutation')
        finally:
            release.set()
            server.shutdown()
            server.server_close()

    def test_pending_operation_retains_original_intent(self):
        self.assertTrue((HERE / 'run.py').exists(), 'Python scenarios implementation is missing')
        import run
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'MDLOGIC_STATE_DIR': directory}):
            files = run.PrivateFiles()
            operation = {'apiOrigin': 'https://api.example.com', 'method': 'POST', 'path': '/api/v1/projects/p/artifacts', 'body': {'content': '# Original'}}
            files.save('pending-02.json', operation, exclusive=True)
            with self.assertRaises(run.ExampleError):
                files.save('pending-02.json', operation, exclusive=True)
            saved = Path(directory) / 'pending-02.json'
            self.assertEqual(json.loads(saved.read_text()), operation)
            self.assertEqual(saved.stat().st_mode & 0o077, 0)

    def test_strict_input_does_not_replace_invalid_bytes(self):
        self.assertTrue((HERE / 'run.py').exists(), 'Python scenarios implementation is missing')
        import run
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'report.md'
            source.write_bytes(b'# bad\xff')
            with patch.dict(os.environ, {'MDLOGIC_INPUT': str(source)}), self.assertRaises(run.ExampleError):
                run.input_text('unused')
            self.assertEqual(source.read_bytes(), b'# bad\xff')
            source.write_bytes(b'# valid\r\nreport\r\n')
            with patch.dict(os.environ, {'MDLOGIC_INPUT': str(source)}):
                self.assertEqual(run.input_text('unused'), '# valid\r\nreport\r\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
