"""Focused local checks; the root suite exercises the complete scenario matrix."""

import hashlib
import hmac
import json
import os
import queue
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import api
import receiver
import scenarios
import state

HERE = Path(__file__).resolve().parent


class PythonExamples(unittest.TestCase):
    def test_transport_helpers_and_signature_contract(self):
        self.assertTrue((HERE / 'api.py').exists(), 'Python transport implementation is missing')
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

    def test_signature_uses_original_timestamp_text(self):
        raw = b'{"id":"event-1","type":"document.updated"}'
        timestamp = '001000'
        signature = hmac.new(
            b'whsec_synthetic', timestamp.encode() + b'.' + raw, hashlib.sha256
        ).hexdigest()
        self.assertTrue(
            receiver.verify_signature(
                f't={timestamp},v1={signature}', raw, 'whsec_synthetic', now=1000
            )
        )
        self.assertFalse(
            receiver.verify_signature(
                f't=1000,v1={signature}', raw, 'whsec_synthetic', now=1000
            )
        )

    def test_oversized_numeric_retry_after_is_refused(self):
        for header in ('9' * 400, '9' * 5000, '0' * 5000 + '6'):
            with self.subTest(digits=len(header)):
                self.assertIsNone(api.retry_delay(header, 0, now=1000))
        self.assertGreaterEqual(api.retry_delay('0' * 5000 + '2', 0, now=1000), 2)

    def test_timed_out_request_cannot_reconnect_and_send_late(self):
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
                result = api.send(
                    'POST',
                    f'http://127.0.0.1:{server.server_port}/create',
                    {},
                    b'{}',
                    timeout=0.1,
                )
                outcome.put(result)
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
        self.assertTrue((HERE / 'state.py').exists(), 'Python state helpers are missing')
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {'MDLOGIC_STATE_DIR': directory}),
        ):
            files = state.PrivateFiles()
            operation = {
                'apiOrigin': 'https://api.example.com',
                'method': 'POST',
                'path': '/api/v1/projects/p/artifacts',
                'body': {'content': '# Original'},
            }
            files.save('pending-02.json', operation, exclusive=True)
            with self.assertRaises(state.ExampleError):
                files.save('pending-02.json', operation, exclusive=True)
            saved = Path(directory) / 'pending-02.json'
            self.assertEqual(json.loads(saved.read_text()), operation)
            self.assertEqual(saved.stat().st_mode & 0o077, 0)

    def test_strict_input_does_not_replace_invalid_bytes(self):
        self.assertTrue((HERE / 'state.py').exists(), 'Python state helpers are missing')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'report.md'
            source.write_bytes(b'# bad\xff')
            with (
                patch.dict(os.environ, {'MDLOGIC_INPUT': str(source)}),
                self.assertRaises(state.ExampleError),
            ):
                state.input_text('unused')
            self.assertEqual(source.read_bytes(), b'# bad\xff')
            source.write_bytes(b'# valid\r\nreport\r\n')
            with patch.dict(os.environ, {'MDLOGIC_INPUT': str(source)}):
                self.assertEqual(state.input_text('unused'), '# valid\r\nreport\r\n')

    def test_invalid_mapping_is_actionable_and_left_untouched(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {'MDLOGIC_STATE_DIR': directory}),
        ):
            files = state.PrivateFiles()
            mapping = Path(directory) / 'state.json'
            for raw in (b'{"projectId":', b'[]', b'null', b'\xff'):
                with self.subTest(raw=raw):
                    mapping.write_bytes(raw)
                    with self.assertRaisesRegex(api.ExampleError, 'Local state is invalid'):
                        files.load()
                    self.assertEqual(mapping.read_bytes(), raw)

    def test_malformed_history_stops_before_snapshot_or_export(self):
        mapping = {'projectId': 'project-1', 'documentId': 'doc-1'}
        for page in ({}, {'items': [None], 'hasMore': False}):
            with self.subTest(page=page):
                client = Mock()
                client.request.return_value = page
                files = Mock()
                with self.assertRaises(api.ExampleError):
                    scenarios.export_report(client, files, mapping)
                client.request.assert_called_once_with(
                    'GET', '/api/v1/projects/project-1/documents/doc-1/versions?limit=20&offset=0'
                )
                files.save.assert_not_called()

    def test_malformed_event_catalogue_does_not_register_a_destination(self):
        with patch.dict(os.environ, {'MDLOGIC_WEBHOOK_URL': 'https://receiver.example/webhook'}):
            for catalogue in ({}, {'events': 'document.created'}):
                with self.subTest(catalogue=catalogue):
                    client = Mock()
                    client.request.return_value = catalogue
                    files = Mock()
                    with self.assertRaisesRegex(api.ExampleError, 'event catalogue'):
                        scenarios.register_webhook(client, files, {})
                    client.request.assert_called_once_with('GET', '/api/v1/webhooks/events')
                    files.pending.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
