#!/usr/bin/env python3
"""Black-box contract checks. All network traffic stays on ephemeral loopback ports."""
import concurrent.futures, email.utils, hashlib, hmac, http.server, json, os, pathlib, shutil, select, socket, subprocess, sys, tempfile, threading, time, unittest
from urllib.parse import urlsplit, parse_qs
ROOT = pathlib.Path(__file__).resolve().parents[1]
LANGUAGES = {'node': ['node','node/run.mjs'], 'java': ['bash','java/run.sh'], 'shell':['bash','shell/run.sh'], 'go':['bash','go/run.sh'], 'python':['python3','python/run.py'], 'csharp-docker':['bash','csharp/docker.sh'], 'csharp':['dotnet','run','--project','csharp','--']}
for language in ['node','java','go','python','shell']:
    LANGUAGES[language+'-docker']=['bash','containers/run.sh',language]
SELECTED = sys.argv[1:] or ['node','java','shell','go','python','csharp']
unknown=set(SELECTED)-set(LANGUAGES)
if unknown: raise SystemExit('Unknown language: '+', '.join(sorted(unknown)))
sys.argv = sys.argv[:1]
EVENTS = ['document.created','document.updated','project.created','project.updated','share.created']
SECRET = 'whsec_synthetic_only'
TOKEN = 'synthetic-bearer-never-live'

class Mock(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self): self.route()
    def do_POST(self): self.route()
    def do_PUT(self): self.route()
    def do_PATCH(self): self.route()
    def reply(self,status,data,headers=None):
        raw = data if isinstance(data,bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','text/html' if isinstance(data,bytes) else 'application/json')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('x-request-id','synthetic-request-1')
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError): pass
    def route(self):
        s=self.server; path=urlsplit(self.path).path; method=self.command
        raw=self.rfile.read(int(self.headers.get('Content-Length',0)))
        s.calls.append((method,self.path,raw,dict(self.headers)))
        if path=='/oauth/token':
            values=parse_qs(raw.decode()); assert values['grant_type']==['client_credentials']
            assert values['client_id']==['synthetic-id'] and values['client_secret']==['synthetic-secret']
            assert 'documents:write' in values['scope'][0]
            return self.reply(200,{'access_token':TOKEN,'token_type':'Bearer','expires_in':3600})
        if self.headers.get('Authorization')!='Bearer '+TOKEN: return self.reply(401,{'code':'UNAUTHORIZED','error':'denied'})
        target=(path.endswith('/documents/doc-1') and method=='GET')
        if target and s.mode in ('429-once','429-always','429-long','429-giant','429-date','429-fallback'):
            s.reads+=1
            if s.mode!='429-once' or s.reads==1:
                if s.mode=='429-date' and s.reads>1: pass
                elif s.mode=='429-fallback' and s.reads>1: pass
                else:
                    headers={} if s.mode=='429-fallback' else {'Retry-After':email.utils.formatdate(time.time()+1,usegmt=True) if s.mode=='429-date' else '120' if s.mode=='429-long' else '2147483648' if s.mode=='429-giant' else '0'}
                    return self.reply(429,{'code':'RATE_LIMITED','error':'synthetic'},headers)
        if target and s.mode=='401': return self.reply(401,{'code':'UNAUTHORIZED','error':'synthetic secret must not be logged '+TOKEN})
        if target and s.mode=='redirect': return self.reply(302,{}, {'Location':s.origin+'/should-not-follow'})
        if method=='POST' and path.endswith(('/projects','/artifacts','/shares','/webhooks')) and s.mode=='create-uncertain':
            self.close_connection=True; self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
        if method=='PUT' and path.endswith('/documents/doc-1'):
            if s.mode=='timeout':
                self.send_response(200); self.send_header('Content-Length','100'); self.end_headers(); self.wfile.flush()
                time.sleep(16); self.close_connection=True; return
            if s.mode=='uncertain': self.close_connection=True; self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
            status={'423':423,'409':409,'write429':429}.get(s.mode)
            if status: return self.reply(status,{'code':{423:'CONTENT_TEMPORARILY_READ_ONLY',409:'CONFLICT',429:'RATE_LIMITED'}[status],'error':'synthetic '+TOKEN,'details':{'reason':'data-protection-conversion' if status==423 else 'document-changed','retryable':True}}, {'Retry-After':'0'} if status==429 else {})
        if method=='POST' and path.endswith('/shares') and s.mode=='malformed-share': return self.reply(201,{'share':{'id':'share-1'}})
        if method=='POST' and path.endswith('/webhooks') and s.mode=='malformed-webhook': return self.reply(201,{'webhook':{'id':'hook-1'}})
        body=json.loads(raw) if raw else {}
        if path=='/api/v1/teams/team-1/projects':
            if method=='POST': assert body['mode']=='document'; return self.reply(201,{'project':{'id':'project-1','name':body['name']}})
            assert parse_qs(urlsplit(self.path).query)=={'limit':['50'],'offset':['0']}
            return self.reply(200,{'items':[{'id':'project-1','name':'Report integration example'}],'hasMore':False,'limit':50,'offset':0})
        if path=='/api/v1/projects/project-1' and method=='PATCH':
            assert body['name']=='Report integration example'; return self.reply(200,{'project':{'id':'project-1','name':body['name']}})
        if path=='/api/v1/projects/project-1/artifacts' and method=='POST':
            assert body['ifNotExists'] is True and body['name']=='report.md'
            assert body['content']==(ROOT/'fixtures/report.md').read_text()
            return self.reply(201,{'artifact':{'id':'doc-1','revision':'opaque-rev-1','logicalName':'report.md'},'decision':'create'})
        if path=='/api/v1/projects/project-1/documents/doc-1':
            if method=='GET': return self.reply(200,{'document':{'id':'doc-1','revision':'opaque-rev-1','content':(ROOT/'fixtures/report.md').read_text()}})
            assert method=='PUT' and body['expectedRevision']=='opaque-rev-1'
            assert body['content']==(ROOT/'fixtures/report-updated.md').read_text()
            assert body['changeNote']=='Refresh generated report'
            return self.reply(200,{'document':{'id':'doc-1','revision':'opaque-rev-2'},'decision':'update'})
        if path.endswith('/versions'):
            assert parse_qs(urlsplit(self.path).query)=={'limit':['20'],'offset':['0']}
            return self.reply(200,{'items':[{'id':'version-1'}],'hasMore':True,'offset':0,'limit':20})
        if path.endswith('/versions/version-1'): return self.reply(200,{'version':{'id':'version-1','content':'# Historical report'}})
        if path.endswith('/renders/html'): return self.reply(200,b'<!doctype html><h1>Synthetic report</h1>')
        if path.endswith('/shares'):
            assert body=={'expiresInDays':30}; return self.reply(201,{'share':{'id':'share-1','url':'https://synthetic.invalid/s/secret-share-link'}})
        if path=='/api/v1/webhooks/events': return self.reply(200,{'events':EVENTS})
        if path=='/api/v1/teams/team-1/webhooks':
            assert body['url']=='https://receiver.synthetic.invalid/webhook' and sorted(body['events'])==sorted(EVENTS)
            return self.reply(201,{'webhook':{'id':'hook-1','events':EVENTS},'secret':SECRET,'secretShownOnce':True})
        self.reply(404,{'error':'unexpected route','code':'NOT_FOUND'})

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Mock)
        self.server.calls=[]; self.server.mode='ok'; self.server.reads=0
        self.server.origin='http://127.0.0.1:'+str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.temp=tempfile.TemporaryDirectory(); self.env=os.environ.copy()
        for key in list(self.env):
            if key.startswith('MDLOGIC_'): del self.env[key]
        if any(language.endswith('-docker') for language in SELECTED): self.env['MDLOGIC_CONTAINER_NETWORK']='host'
        self.env.update(MDLOGIC_API_ORIGIN=self.server.origin,MDLOGIC_OAUTH_ISSUER=self.server.origin,MDLOGIC_TOKEN=TOKEN,MDLOGIC_TEAM='team-1',MDLOGIC_WEBHOOK_URL='https://receiver.synthetic.invalid/webhook',MDLOGIC_WEBHOOK_SECRET=SECRET)
    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.temp.cleanup()
    def run_example(self,lang,scenario,success=True):
        result=subprocess.run(LANGUAGES[lang]+[scenario],cwd=ROOT,env=self.env,text=True,capture_output=True,timeout=90)
        combined=result.stdout+result.stderr
        for secret in [TOKEN,SECRET,'synthetic-secret','secret-share-link']:
            self.assertNotIn(secret,combined,lang+' leaked secret')
        self.assertEqual(result.returncode==0,success,f'{lang} {scenario}: {combined}')
        return result
    def prepare(self,lang):
        path=pathlib.Path(self.temp.name)/lang; path.mkdir(exist_ok=True)
        self.env['MDLOGIC_STATE_DIR']=str(path)
        return path
    def seed(self,path): (path/'state.json').write_text(json.dumps({'projectId':'project-1','documentId':'doc-1','revision':'opaque-rev-1'}))
    def test_scenarios_and_failures(self):
        for lang in SELECTED:
            if lang=='csharp' and not shutil.which('dotnet'): print('SKIP csharp: .NET SDK unavailable'); continue
            with self.subTest(language=lang):
                path=self.prepare(lang)
                for scenario in ['01','02','03','04','05','06']: self.run_example(lang,scenario)
                state=json.loads((path/'state.json').read_text()); self.assertEqual(state['revision'],'opaque-rev-2')
                self.assertIn(b'Synthetic report',(path/'report.html').read_bytes())
                self.assertEqual(json.loads((path/'webhook.json').read_text())['secret'],SECRET)
                for filename in ['state.json','share.json','webhook.json','report.html']:
                    self.assertEqual((path/filename).stat().st_mode & 0o077,0,filename+' must be private')
                for repeated in ['02','05','06']:
                    count=len(self.server.calls); self.run_example(lang,repeated,False); self.assertEqual(len(self.server.calls),count,'mapped create/share/destination must stop locally')
                for mode,success,reads in [('429-once',True,2),('429-always',False,3),('429-long',False,1),('429-giant',False,1),('429-date',True,2),('429-fallback',True,2),('401',False,1),('redirect',False,1)]:
                    self.server.mode=mode; self.server.reads=0; self.server.calls=[]
                    result=self.run_example(lang,'03',success)
                    if mode=='401': self.assertIn('synthetic-request-1',result.stdout+result.stderr)
                    self.assertEqual(sum(c[0]=='GET' for c in self.server.calls),reads,lang+' '+mode)
                    self.assertFalse(any('/should-not-follow' in c[1] for c in self.server.calls))
                for mode in ['423','409','write429','uncertain','timeout']:
                    self.server.mode=mode; self.server.calls=[]
                    before=(ROOT/'fixtures/report-updated.md').read_bytes()
                    result=self.run_example(lang,'03',False)
                    if mode in ['423','409','write429']: self.assertIn('synthetic-request-1',result.stdout+result.stderr)
                    self.assertEqual(sum(c[0]=='PUT' for c in self.server.calls),1,lang+' must not retry '+mode)
                    self.assertEqual((ROOT/'fixtures/report-updated.md').read_bytes(),before)
                for scenario in ['01','02']:
                    marker_dir=pathlib.Path(self.temp.name)/(lang+'-pending-'+scenario); marker_dir.mkdir()
                    self.env['MDLOGIC_STATE_DIR']=str(marker_dir)
                    if scenario=='02': (marker_dir/'state.json').write_text(json.dumps({'projectId':'project-1'}))
                    self.server.mode='create-uncertain'; self.server.calls=[]
                    self.run_example(lang,scenario,False)
                    marker=marker_dir/('pending-'+scenario+'.json'); self.assertTrue(marker.exists())
                    self.assertEqual(marker.stat().st_mode & 0o077,0)
                    self.assertIn('/api/v1/',marker.read_text()); self.assertIn(self.server.origin,marker.read_text())
                    count=len(self.server.calls); self.run_example(lang,scenario,False); self.assertEqual(len(self.server.calls),count)
                self.env['MDLOGIC_STATE_DIR']=str(path)
                self.server.mode='ok'; self.server.calls=[]
                del self.env['MDLOGIC_TOKEN']; self.env.update(MDLOGIC_CLIENT_ID='synthetic-id',MDLOGIC_CLIENT_SECRET='synthetic-secret')
                self.run_example(lang,'04'); self.assertEqual(sum(c[1]=='/oauth/token' for c in self.server.calls),1)
                self.env['MDLOGIC_TOKEN']=TOKEN
                print(f'PASS {lang}: 01–06, retry bounds/date/fallback, write refusal/uncertainty, auth, private output, redirects')
    def test_create_recovery_and_input_validation(self):
        for lang in SELECTED:
            if lang=='csharp' and not shutil.which('dotnet'): continue
            with self.subTest(language=lang):
                for scenario in ['05','06']:
                    path=self.prepare(lang+'-uncertain-'+scenario); self.seed(path)
                    self.server.mode='create-uncertain'; self.server.calls=[]
                    self.run_example(lang,scenario,False)
                    marker=path/('pending-'+scenario+'.json'); self.assertTrue(marker.exists())
                    self.assertIn(self.server.origin,marker.read_text())
                    count=sum(c[0]=='POST' for c in self.server.calls)
                    self.run_example(lang,scenario,False)
                    self.assertEqual(sum(c[0]=='POST' for c in self.server.calls),count)
                for scenario in ['02','03']:
                    path=self.prepare(lang+'-invalid-'+scenario)
                    (path/'state.json').write_text(json.dumps({'projectId':'project-1'} if scenario=='02' else {'projectId':'project-1','documentId':'doc-1'}))
                    invalid=path/'invalid.md'; invalid.write_bytes(b'# report\xff')
                    self.env['MDLOGIC_INPUT']=str(invalid); self.server.mode='ok'; self.server.calls=[]
                    self.run_example(lang,scenario,False)
                    self.assertFalse(any(c[0] in ('POST','PUT','PATCH') for c in self.server.calls))
                    self.assertEqual(invalid.read_bytes(),b'# report\xff')
                del self.env['MDLOGIC_INPUT']
                for scenario,mode,filename in [('05','malformed-share','share.json'),('06','malformed-webhook','webhook.json')]:
                    path=self.prepare(lang+'-'+mode); self.seed(path)
                    self.server.mode=mode; self.server.calls=[]
                    self.run_example(lang,scenario,False)
                    self.assertTrue((path/filename).exists(),'retain malformed mutation response privately')
                    self.assertTrue((path/('pending-'+scenario+'.json')).exists())
                    count=sum(c[0]=='POST' for c in self.server.calls); self.run_example(lang,scenario,False)
                    self.assertEqual(sum(c[0]=='POST' for c in self.server.calls),count)
                self.server.mode='ok'
                print(f'PASS {lang}: uncertain share/webhook rerun blocked, strict UTF-8, malformed mutation evidence retained')
    def test_webhook_receivers(self):
        import urllib.request, urllib.error
        for lang in SELECTED:
            if lang=='csharp' and not shutil.which('dotnet'): continue
            with self.subTest(language=lang):
                path=self.prepare(lang)
                with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
                self.env['PORT']=str(port)
                def start():
                    p=subprocess.Popen(LANGUAGES[lang]+['webhook'],cwd=ROOT,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    ready=False
                    for _ in range(400):
                        if p.poll() is not None: self.fail(f'{lang} receiver exited: {p.communicate()}')
                        if select.select([p.stdout],[],[],0)[0]:
                            line=p.stdout.readline().lower()
                            ready=ready or b'listening' in line or b'ready' in line
                        if ready:
                            try:
                                # Probe the new HTTP application, not a lingering Docker port proxy.
                                with urllib.request.urlopen(f'http://127.0.0.1:{port}/__ready',timeout=.1): return p
                            except urllib.error.HTTPError as error:
                                status=error.code; error.close()
                                if status in (404,405,501): return p
                            except (OSError,TimeoutError): pass
                        time.sleep(.05)
                    p.terminate(); p.communicate(timeout=10); self.fail('receiver startup timeout')
                def send(raw,signature,event_id='event-1',event_type='document.updated'):
                    headers={'Content-Type':'application/json','MDL-Signature':signature,'MDL-Event-Id':event_id}
                    if event_type is not None: headers['MDL-Event-Type']=event_type
                    req=urllib.request.Request(f'http://127.0.0.1:{port}/webhook',raw,headers)
                    try:
                        with urllib.request.urlopen(req,timeout=4) as response: return response.status
                    except urllib.error.HTTPError as error: error.read(); error.close(); return error.code
                raw=json.dumps({'id':'event-1','type':'document.updated','created':'2026-10-29T00:00:00Z','teamId':'team-1','actor':{'type':'system','id':None},'data':{'object':{'id':'doc-1','logicalName':'café.md'}}},ensure_ascii=False).encode()
                def sign(body,t=None):
                    t=int(time.time()) if t is None else t
                    return f't={t},v1='+hmac.new(SECRET.encode(),str(t).encode()+b'.'+body,hashlib.sha256).hexdigest()
                process=start()
                try:
                    self.assertEqual(send(raw,'t=1,v1='+'0'*64),401)
                    self.assertEqual(send(raw,sign(raw,int(time.time())-301)),401)
                    self.assertEqual(send(raw,sign(raw,int(time.time())+301)),401)
                    self.assertEqual(send(raw+b' ',sign(raw)),401)
                    self.assertEqual(send(raw,sign(raw),'mismatch'),400)
                    self.assertEqual(send(raw,sign(raw),'event-1','share.created'),400)
                    empty=raw.replace(b'\"type\": \"document.updated\"',b'\"type\": \"\"')
                    self.assertEqual(send(empty,sign(empty),event_type=None),400)
                    self.assertEqual(send(raw,sign(raw)+',v1='+'0'*64),202)
                    self.assertEqual(send(raw,sign(raw)),200)
                    raw2=raw.replace(b'event-1',b'event-2')
                    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                        statuses=list(pool.map(lambda _:send(raw2,sign(raw2),'event-2'),range(8)))
                    self.assertEqual(statuses.count(202),1); self.assertEqual(statuses.count(200),7)
                    for entry in (path/'inbox').glob('*.json'): json.loads(entry.read_bytes())
                finally: process.terminate(); process.communicate(timeout=10)
                # Reuse the inbox on a fresh listener; avoid stale container port forwarding.
                with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
                self.env['PORT']=str(port)
                process=start()
                try: self.assertEqual(send(raw,sign(raw)),200)
                finally: process.terminate(); process.communicate(timeout=10)
                print(f'PASS {lang}: webhook valid, duplicate/restart, bad/stale/future/tampered signature, signed ID/type checks, multi-v1')

if __name__=='__main__': unittest.main(verbosity=2)
