"""Small local behavior checks; full cross-language tests live in ../tests."""
import json, os, subprocess, tempfile, threading, unittest, socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
class Handler(BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *args): pass
    def do_GET(self):
        self.calls.append(('GET', self.path, None))
        body = json.dumps({'document': {'id': 'doc-1', 'revision': 'fresh', 'content': '# old'}}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append(('POST', self.path, body))
        self.close_connection = True
        self.connection.shutdown(socket.SHUT_RDWR); self.connection.close()
    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append(('PUT', self.path, body))
        self.send_response(423); self.end_headers()
        self.wfile.write(b'{"code":"CONTENT_TEMPORARILY_READ_ONLY","details":{"reason":"data-protection-conversion","retryable":true}}')
class ShellTests(unittest.TestCase):
    def test_uncertain_project_create_blocks_another_create(self):
        Handler.calls=[]
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                env={**os.environ,'MDLOGIC_TOKEN':'synthetic-only','MDLOGIC_TEAM':'team-1','MDLOGIC_API_ORIGIN':f'http://127.0.0.1:{server.server_port}','MDLOGIC_STATE_DIR':d}
                for _ in range(2):
                    result=subprocess.run(['bash','shell/run.sh','01'],cwd=ROOT,env=env,capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0)
                self.assertEqual(len(Handler.calls),1)
                marker=Path(d)/'pending-01.json'
                self.assertTrue(marker.exists())
                self.assertEqual(marker.stat().st_mode & 0o077,0)
                record=json.loads(marker.read_text())
                self.assertEqual(record['body']['name'],'Report integration example')
                self.assertEqual(record['path'],'/api/v1/teams/team-1/projects')
                self.assertEqual(record['apiOrigin'],env['MDLOGIC_API_ORIGIN'])
                self.assertEqual(record['method'],'POST')
        finally: server.shutdown(); server.server_close()
    def test_refuses_external_plain_http_without_contacting_it(self):
        with tempfile.TemporaryDirectory() as d:
            result=subprocess.run(['bash','shell/run.sh','01'],cwd=ROOT,env={**os.environ,'MDLOGIC_TOKEN':'synthetic-only','MDLOGIC_API_ORIGIN':'http://example.invalid','MDLOGIC_STATE_DIR':d},capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Configuration',result.stderr)
    def test_write_refusal_preserves_source_and_does_not_retry(self):
        Handler.calls=[]
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                source=Path(d)/'input.md'; source.write_text('# generated café\n')
                state=Path(d)/'state.json'; state.write_text(json.dumps({'projectId':'p-1','documentId':'doc-1','revision':'old'}))
                env={**os.environ,'MDLOGIC_TOKEN':'synthetic-only','MDLOGIC_API_ORIGIN':f'http://127.0.0.1:{server.server_port}','MDLOGIC_STATE_DIR':d,'MDLOGIC_INPUT':str(source)}
                result=subprocess.run(['bash','shell/run.sh','03'],cwd=ROOT,env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('CONTENT_TEMPORARILY_READ_ONLY',result.stderr)
                self.assertEqual(source.read_text(),'# generated café\n')
                self.assertEqual(len([c for c in Handler.calls if c[0]=='PUT']),1)
                self.assertEqual(Handler.calls[-1][2]['expectedRevision'],'fresh')
        finally: server.shutdown(); server.server_close()
if __name__=='__main__': unittest.main()
