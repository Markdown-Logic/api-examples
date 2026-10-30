#!/usr/bin/env python3
"""Small durable inbox receiver. Python stdlib keeps raw-byte HMAC checks explicit."""
import hashlib, hmac, json, os, re, sys, tempfile, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 1024 * 1024

def verify(header, raw, secret, now=None):
    fields=[part.strip() for part in header.split(',')]
    timestamps=[part[2:] for part in fields if part.startswith('t=')]
    if len(timestamps)!=1 or not re.fullmatch(r'[0-9]{1,12}',timestamps[0]): return False
    timestamp=int(timestamps[0])
    if timestamp<=0 or abs(int(time.time() if now is None else now)-timestamp)>300: return False
    expected=hmac.new(secret.encode(),str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return any(re.fullmatch(r'[0-9a-f]{64}',part[3:]) is not None and hmac.compare_digest(part[3:],expected)
               for part in fields if part.startswith('v1='))

def accept(inbox, event):
    """Write+fsync before atomic link: a concurrent duplicate cannot see a partial file."""
    key=hashlib.sha256(event['id'].encode()).hexdigest()
    fd, temporary=tempfile.mkstemp(prefix='.pending-',dir=inbox)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(event,f,ensure_ascii=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
        try: os.link(temporary,inbox/(key+'.json'))
        except FileExistsError: return False
        directory=os.open(inbox,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        return True
    finally: os.unlink(temporary)

class Receiver(BaseHTTPRequestHandler):
    secret=''; inbox=None
    def log_message(self,*args): pass  # No bodies, actor emails, URLs or secrets in logs.
    def setup(self):
        super().setup(); self.connection.settimeout(15)
    def reply(self,status):
        self.send_response(status); self.send_header('Content-Length','0'); self.end_headers()
    def do_POST(self):
        if self.path!='/webhook': self.reply(404); return
        if self.headers.get('Transfer-Encoding'): self.reply(400); return
        try:
            length=int(self.headers.get('Content-Length','-1'))
            if length<0: self.reply(400); return
            if length>MAX_BODY: self.reply(413); return
            raw=self.rfile.read(length)
            if len(raw)!=length: self.reply(400); return
            if not verify(self.headers.get('MDL-Signature',''),raw,self.secret): self.reply(401); return
            event=json.loads(raw)
            if (not isinstance(event,dict) or not isinstance(event.get('id'),str)
                or not event['id'] or len(event['id'].encode())>512
                or not isinstance(event.get('type'),str) or not event['type']
                or event['id']!=self.headers.get('MDL-Event-Id')
                or (self.headers.get('MDL-Event-Type') is not None and event['type']!=self.headers['MDL-Event-Type'])):
                self.reply(400); return
            self.reply(202 if accept(self.inbox,event) else 200)
        except (ValueError,UnicodeError): self.reply(400)
        except (OSError,TimeoutError): self.reply(503)

def main():
    os.umask(0o077)
    secret=os.environ.get('MDLOGIC_WEBHOOK_SECRET','')
    if not secret: sys.exit('Set MDLOGIC_WEBHOOK_SECRET to the once-only signing secret.')
    inbox=Path(os.environ.get('MDLOGIC_STATE_DIR','.local/shell'))/'inbox'
    inbox.mkdir(parents=True,exist_ok=True); inbox.chmod(0o700); inbox.parent.chmod(0o700)
    Receiver.secret=secret; Receiver.inbox=inbox
    port=int(os.environ.get('PORT','8080'))
    if not 1<=port<=65535: sys.exit('PORT must be 1..65535.')
    bind=os.environ.get('MDLOGIC_WEBHOOK_BIND','127.0.0.1')
    if bind not in ('127.0.0.1','0.0.0.0'): sys.exit('Invalid webhook bind address.')
    server=ThreadingHTTPServer((bind,port),Receiver)
    print(f'Webhook inbox listening on http://127.0.0.1:{port}/webhook',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
if __name__=='__main__': main()
