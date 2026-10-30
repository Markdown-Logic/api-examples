"""Small localhost behavior checks; shared contract tests live in ../tests."""

import hashlib
import hmac
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from webhook import verify

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    """Return one live revision, lose create responses, and refuse update writes."""

    calls = []
    response_body = None

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.calls.append(("GET", self.path, None))
        response = self.response_body
        if response is None:
            response = {"document": {"id": "doc-1", "revision": "fresh", "content": "# old"}}
        body = json.dumps(response).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(("POST", self.path, body))
        self.close_connection = True
        self.connection.shutdown(socket.SHUT_RDWR)
        self.connection.close()

    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(("PUT", self.path, body))
        self.send_response(423)
        self.end_headers()
        self.wfile.write(
            b'{"code":"CONTENT_TEMPORARILY_READ_ONLY",'
            b'"details":{"reason":"data-protection-conversion","retryable":true}}'
        )


class ShellTests(unittest.TestCase):
    def setUp(self):
        Handler.calls = []
        Handler.response_body = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.env = {
            **os.environ,
            "MDLOGIC_TOKEN": "synthetic-only",
            "MDLOGIC_TEAM": "team-1",
            "MDLOGIC_API_ORIGIN": f"http://127.0.0.1:{self.server.server_port}",
            "MDLOGIC_STATE_DIR": str(self.directory),
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def run_example(self, scenario):
        return subprocess.run(
            ["bash", "shell/run.sh", scenario],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_uncertain_project_create_blocks_another_create(self):
        for _ in range(2):
            result = self.run_example("01")
            self.assertNotEqual(result.returncode, 0)

        self.assertEqual(len(Handler.calls), 1)
        marker = self.directory / "pending-01.json"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.stat().st_mode & 0o077, 0)
        record = json.loads(marker.read_text())
        self.assertEqual(record["body"]["name"], "Report integration example")
        self.assertEqual(record["path"], "/api/v1/teams/team-1/projects")
        self.assertEqual(record["apiOrigin"], self.env["MDLOGIC_API_ORIGIN"])
        self.assertEqual(record["method"], "POST")

    def test_refuses_external_plain_http_without_contacting_it(self):
        self.env["MDLOGIC_API_ORIGIN"] = "http://example.invalid"
        result = self.run_example("01")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Configuration", result.stderr)
        self.assertEqual(Handler.calls, [])

    def test_invalid_mapping_stops_before_any_request(self):
        state = self.directory / "state.json"
        for content in ("null", "[]", '"text"', "{broken", "{} {}"):
            with self.subTest(content=content):
                state.write_text(content)
                result = self.run_example("01")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("State file must contain one JSON object", result.stderr)
                self.assertEqual(state.read_text(), content)
                self.assertEqual(Handler.calls, [])

    def test_invalid_history_id_stops_before_snapshot_or_export(self):
        (self.directory / "state.json").write_text(
            json.dumps({"projectId": "p-1", "documentId": "doc-1"})
        )
        for item in ({"id": 123}, {"id": ""}, {}, "unexpected"):
            with self.subTest(item=item):
                Handler.calls = []
                Handler.response_body = {"items": [item], "hasMore": False}
                result = self.run_example("04")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("valid history snapshot ID", result.stderr)
                self.assertEqual(len(Handler.calls), 1)
                self.assertFalse((self.directory / "report.html").exists())

    def test_invalid_event_catalogue_stops_before_registration(self):
        self.env["MDLOGIC_WEBHOOK_URL"] = "https://receiver.synthetic.invalid/webhook"
        for response in ({}, {"events": "document.created"}, {"events": {}}):
            with self.subTest(response=response):
                Handler.calls = []
                Handler.response_body = response
                result = self.run_example("06")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("event catalogue", result.stderr)
                self.assertEqual(len(Handler.calls), 1)
                self.assertFalse((self.directory / "pending-06.json").exists())

    def test_write_refusal_preserves_source_and_does_not_retry(self):
        source = self.directory / "input.md"
        source.write_text("# generated café\n")
        state = self.directory / "state.json"
        state.write_text(
            json.dumps({"projectId": "p-1", "documentId": "doc-1", "revision": "old"})
        )
        self.env["MDLOGIC_INPUT"] = str(source)
        result = self.run_example("03")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONTENT_TEMPORARILY_READ_ONLY", result.stderr)
        self.assertEqual(source.read_text(), "# generated café\n")
        self.assertEqual(sum(call[0] == "PUT" for call in Handler.calls), 1)
        self.assertEqual(Handler.calls[-1][2]["expectedRevision"], "fresh")


class WebhookValidationTests(unittest.TestCase):
    def test_signature_uses_exact_timestamp_text(self):
        body = b'{"id":"synthetic-event","type":"document.updated"}'
        now = int(time.time())
        timestamp = "0" + str(now)
        secret = "synthetic-signing-secret"
        digest = hmac.new(
            secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        self.assertTrue(verify(f"t={timestamp},v1={digest}", body, secret, now))

        normalized = hmac.new(
            secret.encode(), str(now).encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        self.assertFalse(verify(f"t={timestamp},v1={normalized}", body, secret, now))


if __name__ == "__main__":
    unittest.main()
