#!/usr/bin/env python3
"""Only URL validation, Retry-After parsing and form encoding; HTTP uses curl."""
import os, sys, math, time, random
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlencode

def origin(value):
    u=urlsplit(value)
    if (u.scheme not in ('http','https') or not u.hostname or u.username or u.password
        or u.path not in ('','/') or u.query or u.fragment
        or (u.scheme=='http' and u.hostname not in ('localhost','127.0.0.1','::1'))):
        raise ValueError('Use an HTTPS origin; HTTP is allowed only for literal localhost.')
    _=u.port
    return value.rstrip('/')

try:
    if sys.argv[1]=='origin': print(origin(sys.argv[2]))
    elif sys.argv[1]=='wait':
        raw=sys.argv[2].strip(); fallback=int(sys.argv[3])
        if raw.isdigit():
            digits=raw.lstrip('0') or '0'
            if len(digits)>1 or digits>'5': raise ValueError('Retry-After exceeds budget.')
            wait=int(digits)
        else:
            try: wait=math.ceil(parsedate_to_datetime(raw).timestamp()-time.time())
            except (ValueError,TypeError,OverflowError): wait=fallback
        wait=max(0,wait)
        if wait>5: raise ValueError('Retry-After exceeds this example’s five-second wait budget; retry deliberately later.')
        print(min(5.0, wait + random.uniform(0.02,0.10)))
    elif sys.argv[1]=='input':
        from pathlib import Path
        Path(sys.argv[2]).read_bytes().decode('utf-8',errors='strict')
    elif sys.argv[1]=='form':
        print(urlencode({'grant_type':'client_credentials','client_id':os.environ['MDLOGIC_CLIENT_ID'],
                        'client_secret':os.environ['MDLOGIC_CLIENT_SECRET'],
                        'scope':'projects:read documents:read documents:write'}),end='')
except (ValueError,KeyError):
    print('Configuration or Retry-After exceeds the example’s allowed bounds.',file=sys.stderr); sys.exit(1)
