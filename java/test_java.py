"""Localhost behavioral tests; no credentials, providers or tenant writes."""
import hashlib, hmac, http.client, json, os, pathlib, socket, subprocess, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).resolve().parent.parent
class Handler(BaseHTTPRequestHandler):
    calls = []
    status = 200
    retries = 0
    def log_message(self, *_): pass
    def send_json(self, status, body, headers=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(json.dumps(body).encode())
    def do_GET(self):
        type(self).calls.append(('GET', self.path, None))
        if self.path.endswith('/documents/doc-1'):
            if type(self).retries:
                type(self).retries -= 1
                return self.send_json(429, {'code':'RATE_LIMITED'}, {'Retry-After':'0'})
            return self.send_json(200, {'document': {'id':'doc-1','revision':'opaque-r1','content':'# Original'}})
        return self.send_json(404, {'code':'NOT_FOUND'})
    def do_POST(self):
        raw=self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).calls.append(("POST", self.path, json.loads(raw)))
        self.close_connection=True
        self.connection.shutdown(socket.SHUT_RDWR)
        self.connection.close()
    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).calls.append(('PUT', self.path, body))
        if type(self).status != 200:
            return self.send_json(type(self).status, {'code': {401:'INVALID_TOKEN',409:'CONFLICT',423:'CONTENT_TEMPORARILY_READ_ONLY',429:'RATE_LIMITED'}[type(self).status], 'details': {'reason':'document-changed','retryable':True}})
        return self.send_json(200, {'document': {'id':'doc-1','revision':'opaque-r2'}, 'decision':'update'})
class JavaExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.state=pathlib.Path(self.tmp.name)
        (self.state/'state.json').write_text(json.dumps({'projectId':'project-1','documentId':'doc-1','revision':'old'}))
        self.env={**os.environ,'MDLOGIC_API_ORIGIN':f'http://127.0.0.1:{self.server.server_port}','MDLOGIC_TOKEN':'synthetic-token','MDLOGIC_STATE_DIR':str(self.state)}
        Handler.calls=[]; Handler.status=200; Handler.retries=0
    def tearDown(self): self.tmp.cleanup()
    def run_example(self): return subprocess.run(['bash','java/run.sh','03'],cwd=ROOT,env=self.env,capture_output=True,text=True,timeout=30)
    def test_guarded_update(self):
        result=self.run_example(); self.assertEqual(result.returncode,0,result.stderr)
        writes=[c for c in Handler.calls if c[0]=='PUT']; self.assertEqual(len(writes),1)
        self.assertEqual(writes[0][2]['expectedRevision'],'opaque-r1')
        self.assertEqual(writes[0][2]['content'],(ROOT/'fixtures/report-updated.md').read_text())
        self.assertEqual(json.loads((self.state/'state.json').read_text())['revision'],'opaque-r2')
    def test_refused_writes_are_single_attempt_and_preserve_input(self):
        content=(ROOT/'fixtures/report-updated.md').read_bytes()
        for status in (401,409,423,429):
            with self.subTest(status=status):
                Handler.calls=[]; Handler.status=status
                result=self.run_example(); self.assertNotEqual(result.returncode,0)
                self.assertEqual(sum(c[0]=='PUT' for c in Handler.calls),1)
                self.assertEqual((ROOT/'fixtures/report-updated.md').read_bytes(),content)
                self.assertEqual(json.loads((self.state/'state.json').read_text())['revision'],'old')
                self.assertNotIn('synthetic-token',result.stderr)
    def test_get_429_retries_are_bounded(self):
        Handler.retries=2; result=self.run_example(); self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(sum(c[0]=='GET' for c in Handler.calls),3)
        Handler.calls=[]; Handler.retries=4
        result=self.run_example(); self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(Handler.calls),3)
    def test_pending_create_retains_original_target_and_blocks_repeat(self):
        self.env['MDLOGIC_TEAM']='team-original'
        for scenario,seed,path in [('01',{},'/api/v1/teams/team-original/projects'),('02',{'projectId':'project-original'},'/api/v1/projects/project-original/artifacts')]:
            with self.subTest(scenario=scenario):
                (self.state/'state.json').write_text(json.dumps(seed))
                Handler.calls=[]
                result=subprocess.run(['bash','java/run.sh',scenario],cwd=ROOT,env=self.env,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(result.returncode,0)
                marker=json.loads((self.state/f'pending-{scenario}.json').read_text())
                self.assertEqual(marker['apiOrigin'],self.env['MDLOGIC_API_ORIGIN'])
                self.assertEqual(marker['method'],'POST')
                self.assertEqual(marker['path'],path)
                self.assertEqual(marker['body'],Handler.calls[0][2])
                self.assertNotIn('synthetic-token',json.dumps(marker))
                count=len(Handler.calls)
                self.env['MDLOGIC_TEAM']='changed-team'
                result=subprocess.run(['bash','java/run.sh',scenario],cwd=ROOT,env=self.env,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(len(Handler.calls),count)
                self.env['MDLOGIC_TEAM']='team-original'
    def test_webhook_authentication_and_persistent_dedup(self):
        sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]; sock.close()
        env={**self.env,'MDLOGIC_WEBHOOK_SECRET':'whsec_synthetic','PORT':str(port)}
        def start():
            proc=subprocess.Popen(['bash','java/run.sh','webhook'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1): return proc
                except OSError: time.sleep(.05)
            proc.kill(); self.fail('receiver did not start: '+proc.stderr.read().decode())
        def deliver(body,event_id,signature):
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
            conn.request('POST','/webhook',body,{'MDL-Signature':signature,'MDL-Event-Id':event_id,'MDL-Event-Type':'document.updated'})
            response=conn.getresponse(); response.read(); conn.close(); return response.status
        body=b'{"id":"evt-1","type":"document.updated","data":{"object":{"id":"doc-1"}}}'
        t=str(int(time.time())); digest=hmac.new(b'whsec_synthetic',t.encode()+b'.'+body,hashlib.sha256).hexdigest()
        signature=f't={t},v1={"0"*64},v1={digest}'
        proc=start()
        try:
            self.assertEqual(deliver(body,'evt-1','t=1,v1=bad'),401)
            self.assertEqual(deliver(body,'different',signature),400)
            self.assertEqual(deliver(body,'evt-1',signature),202)
            self.assertEqual(deliver(body,'evt-1',signature),200)
        finally: proc.terminate(); proc.wait(timeout=5); proc.stderr.close()
        proc=start()
        try: self.assertEqual(deliver(body,'evt-1',signature),200)
        finally: proc.terminate(); proc.wait(timeout=5); proc.stderr.close()
        self.assertEqual(len(list((self.state/'inbox').glob('*.json'))),1)
if __name__=='__main__': unittest.main(verbosity=2)
