"""Run one small report-integration scenario from the repository root."""
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import quote, urlsplit

from api import Api, ExampleError, required
from receiver import receive

EVENTS = ['document.created', 'document.updated', 'project.created', 'project.updated', 'share.created']


class PrivateFiles:
    def __init__(self):
        self.directory = Path(os.environ.get('MDLOGIC_STATE_DIR', '.local/python'))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def save(self, name, value, exclusive=False):
        raw = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        target = self.directory / name
        if exclusive:
            try:
                with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
            except FileExistsError:
                raise ExampleError('A create is pending. Reconcile its original target and payload before another attempt.') from None
            return
        with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.pending-', delete=False) as output:
            temporary = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self):
        try:
            state = json.loads((self.directory / 'state.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        if not isinstance(state, dict):
            raise ExampleError('Local state is invalid. Review it before continuing.')
        return state

    def refuse_existing(self, name):
        if (self.directory / name).exists():
            raise ExampleError('A saved response exists. Review it before creating another share or destination.')

    def pending(self, number, api, path, body):
        self.save('pending-' + number + '.json', {'apiOrigin': api.base, 'method': 'POST', 'path': path, 'body': body}, exclusive=True)

    def done(self, number):
        (self.directory / ('pending-' + number + '.json')).unlink()


def input_text(fallback):
    try:
        return Path(os.environ.get('MDLOGIC_INPUT', fallback)).read_bytes().decode('utf-8', errors='strict')
    except (OSError, UnicodeError):
        raise ExampleError('Input must be readable UTF-8 text. No mutation was sent; input is unchanged.') from None


def field(value, key):
    return value.get(key) if isinstance(value, dict) else None


def scenario(number):
    files = PrivateFiles()
    if number == 'webhook':
        return receive(files.directory)
    if number not in {'01', '02', '03', '04', '05', '06'}:
        raise ExampleError('Choose 01..06 or webhook; run from the repository root.')
    state = files.load()
    if number == '01' and state.get('projectId'):
        raise ExampleError('Project is already mapped. Reuse its stable ID.')
    if number == '02' and state.get('documentId'):
        raise ExampleError('Report is already mapped. Use 03 to update it.')
    api = Api()
    team = lambda: quote(required(os.environ.get('MDLOGIC_TEAM'), 'MDLOGIC_TEAM'), safe='')
    project = lambda: '/api/v1/projects/' + quote(required(state.get('projectId'), 'projectId (01)'), safe='')
    document = lambda: project() + '/documents/' + quote(required(state.get('documentId'), 'documentId (02)'), safe='')
    if number == '01':
        path = '/api/v1/teams/' + team() + '/projects'
        body = {'name': 'Report integration example', 'mode': 'document'}
        files.pending(number, api, path, body)
        result = api.request('POST', path, body)
        state['projectId'] = required(field(result.get('project'), 'id'), 'valid project ID')
        files.save('state.json', state)
        files.done(number)
        page = api.request('GET', path + '?limit=50&offset=0')
        api.request('PATCH', project(), {'name': 'Report integration example'})
        return {'scenario': number, 'projectId': state['projectId'], 'listed': len(page['items']), 'hasMore': page.get('hasMore')}
    if number == '02':
        path = project() + '/artifacts'
        body = {'name': 'report.md', 'content': input_text('fixtures/report.md'), 'format': 'markdown', 'ifNotExists': True}
        files.pending(number, api, path, body)
        result = api.request('POST', path, body)
        state['documentId'] = required(field(result.get('artifact'), 'id'), 'valid document ID')
        state['revision'] = required(field(result.get('artifact'), 'revision'), 'valid revision')
        files.save('state.json', state)
        files.done(number)
        return {'scenario': number, 'documentId': state['documentId'], 'decision': result.get('decision')}
    if number == '03':
        content = input_text('fixtures/report-updated.md')
        current = api.request('GET', document())
        # Real products must review/merge intervening user edits before replacing full source.
        body = {'content': content, 'expectedRevision': required(field(current.get('document'), 'revision'), 'live revision'),
                'changeNote': 'Refresh generated report'}
        result = api.request('PUT', document(), body)
        state['revision'] = required(field(result.get('document'), 'revision'), 'updated revision')
        files.save('state.json', state)
        return {'scenario': number, 'documentId': state['documentId'], 'decision': result.get('decision')}
    if number == '04':
        page = api.request('GET', document() + '/versions?limit=20&offset=0')
        if not isinstance(page.get('items'), list) or not isinstance(page.get('hasMore'), bool):
            raise ExampleError('Malformed history page; export stopped.')
        if page['items']:
            api.request('GET', document() + '/versions/' + quote(required(page['items'][0].get('id'), 'version ID'), safe=''))
        files.save('report.html', api.request('GET', document() + '/renders/html', binary=True))
        return {'scenario': number, 'versions': len(page['items']), 'hasMore': page['hasMore'], 'exportFile': str(files.directory / 'report.html')}
    if number == '05':
        files.refuse_existing('share.json')
        path, body = document() + '/shares', {'expiresInDays': 30}
        files.pending(number, api, path, body)
        result = api.request('POST', path, body)
        files.save('share.json', result)
        share_id = required(field(result.get('share'), 'id'), 'valid share ID')
        required(field(result.get('share'), 'url'), 'valid share URL')
        files.done(number)
        return {'scenario': number, 'shareId': share_id, 'shareFile': str(files.directory / 'share.json')}
    files.refuse_existing('webhook.json')
    callback = required(os.environ.get('MDLOGIC_WEBHOOK_URL'), 'MDLOGIC_WEBHOOK_URL')
    url = urlsplit(callback)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
        raise ExampleError('Use an explicit public HTTPS webhook URL without userinfo or fragment.')
    catalogue = api.request('GET', '/api/v1/webhooks/events')
    if not isinstance(catalogue.get('events'), list) or not all(event in catalogue['events'] for event in EVENTS):
        raise ExampleError('The live event catalogue does not support all requested events.')
    path = '/api/v1/teams/' + team() + '/webhooks'
    body = {'url': callback, 'events': EVENTS, 'description': 'Generated report lifecycle'}
    files.pending(number, api, path, body)
    result = api.request('POST', path, body)
    files.save('webhook.json', result)
    webhook_id = required(field(result.get('webhook'), 'id'), 'valid webhook ID')
    required(result.get('secret'), 'once-only signing secret')
    files.done(number)
    return {'scenario': number, 'webhookId': webhook_id, 'secretFile': str(files.directory / 'webhook.json')}


def main():
    try:
        if len(sys.argv) != 2:
            raise ExampleError('Choose 01..06 or webhook.')
        result = scenario(sys.argv[1])
        if result is not None:
            print(json.dumps(result))
    except ExampleError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print('Operation failed. Keep input and private state; reconcile any uncertain write before retrying.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
