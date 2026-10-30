#!/usr/bin/env python3
"""Read-only verification of canonical MDL reference URLs; no credentials."""
import concurrent.futures, datetime, hashlib, json, subprocess, tempfile
from pathlib import Path
urls = [
 'https://api.markdownlogic.com/',
 'https://api.markdownlogic.com/api/v1/openapi.json',
 'https://auth.markdownlogic.com/.well-known/oauth-authorization-server',
 'https://markdownlogic.com/help/en/use-the-rest-api',
 'https://markdownlogic.com/help/en/receive-webhooks',
 'https://markdownlogic.com/help/en/install-the-cli',
 'https://markdownlogic.com/help/en/export-from-the-cli',
 'https://markdownlogic.com/help/en/share-a-document',
 'https://markdownlogic.com/help/en/automate-team-documents',
]
def check(url):
    with tempfile.TemporaryDirectory() as directory:
        target=Path(directory)/'body'
        result=subprocess.run(['curl','--disable','--silent','--show-error','--max-time','20','--proto','=https','--output',str(target),'--write-out','%{http_code}\n%{url_effective}\n%{content_type}',url],capture_output=True,text=True)
        if result.returncode: return {'url':url,'error':'curl exit '+str(result.returncode)}
        fields=result.stdout.splitlines()
        return {'url':url,'status':int(fields[0]),'finalUrl':fields[1],'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'contentType':fields[2] if len(fields)>2 else ''}

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(check,urls))
report={'checkedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'links':results}
Path('reference/link-check.json').write_text(json.dumps(report,indent=2)+'\n')
for result in results: print(result['url'], result.get('status',result.get('error')))
if any(result.get('status')!=200 for result in results): raise SystemExit(1)
