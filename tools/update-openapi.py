#!/usr/bin/env python3
"""Fetch the public production specification unchanged; review drift deliberately."""
import argparse, datetime, hashlib, json, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
URL='https://api.markdownlogic.com/api/v1/openapi.json'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--update',action='store_true',help='replace snapshot and download provenance after review')
args=parser.parse_args()
with tempfile.TemporaryDirectory() as temporary:
    fetched=pathlib.Path(temporary)/'openapi.json'
    subprocess.run(['curl','--disable','--fail','--silent','--show-error','--max-time','30','--proto','=https',URL,'--output',str(fetched)],check=True)
    raw=fetched.read_bytes(); document=json.loads(raw)
    if not document.get('openapi','').startswith('3.') or document.get('info',{}).get('title')!='Markdown Logic Platform API':
        raise SystemExit('Unexpected document; snapshot was not changed.')
    if document.get('servers')!=[{'url':'https://api.markdownlogic.com'}]:
        raise SystemExit('Unexpected server origin; snapshot was not changed.')
    current=ROOT/'reference/openapi.json'
    digest=hashlib.sha256(raw).hexdigest()
    print('Fetched',document['info']['version'],digest)
    if not args.update:
        if current.read_bytes()!=raw: raise SystemExit('DRIFT: review the live document, then run --update deliberately. No file changed.')
        print('Snapshot matches production byte-for-byte.'); raise SystemExit(0)
    # Keep the downloaded bytes unchanged. No reformatting, filtering or added paths.
    current.write_bytes(raw)
    manifest={'url':URL,'retrievedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sha256':digest,
              'bytes':len(raw),'openapi':document['openapi'],'infoVersion':document['info']['version'],
              'productionCommit':None,'packagingChanges':'none; verbatim response bytes'}
    (ROOT/'reference/provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Updated snapshot/provenance. Review diff and run python3 tests/reference_check.py before committing.')
