"""Six comparable tasks for an application that stores a generated report."""

import os
from urllib.parse import quote, urlsplit

from api import ExampleError, required
from state import field, input_text, mapped_path

EVENTS = [
    'document.created',
    'document.updated',
    'project.created',
    'project.updated',
    'share.created',
]


def team_path():
    """Address the configured team without treating its ID as URL syntax."""
    team = quote(required(os.environ.get('MDLOGIC_TEAM'), 'MDLOGIC_TEAM'), safe='')
    return f'/api/v1/teams/{team}'


def create_project(api, files, state):
    """01: Create and map a project, then demonstrate a bounded list and update."""
    if state.get('projectId'):
        raise ExampleError('Project is already mapped. Reuse its stable ID.')

    path = team_path() + '/projects'
    body = {'name': 'Report integration example', 'mode': 'document'}
    files.pending('01', api, path, body)
    result = api.request('POST', path, body)
    state['projectId'] = required(field(result.get('project'), 'id'), 'valid project ID')
    # Save the mapping before later calls: a list failure must not cause a new project.
    files.save('state.json', state)
    files.done('01')

    page = api.request('GET', path + '?limit=50&offset=0')
    api.request('PATCH', mapped_path(state, 'project'), {'name': 'Report integration example'})
    return {
        'scenario': '01',
        'projectId': state['projectId'],
        'listed': len(page['items']),
        'hasMore': page.get('hasMore'),
    }


def create_report(api, files, state):
    """02: Store exact generated source once and retain its stable document ID."""
    if state.get('documentId'):
        raise ExampleError('Report is already mapped. Use 03 to update it.')

    path = mapped_path(state, 'project') + '/artifacts'
    body = {
        'name': 'report.md',
        'content': input_text('fixtures/report.md'),
        'format': 'markdown',
        'ifNotExists': True,
    }
    files.pending('02', api, path, body)
    result = api.request('POST', path, body)
    state['documentId'] = required(field(result.get('artifact'), 'id'), 'valid document ID')
    state['revision'] = required(field(result.get('artifact'), 'revision'), 'valid revision')
    files.save('state.json', state)
    files.done('02')
    return {
        'scenario': '02',
        'documentId': state['documentId'],
        'decision': result.get('decision'),
    }


def update_report(api, files, state):
    """03: Replace the fixture with an explicit guard against concurrent edits."""
    content = input_text('fixtures/report-updated.md')
    path = mapped_path(state, 'document')
    current = api.request('GET', path)
    # Real products must review or merge intervening edits before replacing source.
    # A 409 stops here; fetching another revision and retrying would overwrite edits.
    body = {
        'content': content,
        'expectedRevision': required(field(current.get('document'), 'revision'), 'live revision'),
        'changeNote': 'Refresh generated report',
    }
    result = api.request('PUT', path, body)
    state['revision'] = required(field(result.get('document'), 'revision'), 'updated revision')
    files.save('state.json', state)
    return {
        'scenario': '03',
        'documentId': state['documentId'],
        'decision': result.get('decision'),
    }


def export_report(api, files, state):
    """04: Read one history page and snapshot, then explicitly export HTML."""
    path = mapped_path(state, 'document')
    page = api.request('GET', path + '/versions?limit=20&offset=0')
    if not isinstance(page.get('items'), list) or not isinstance(page.get('hasMore'), bool):
        raise ExampleError('Malformed history page; export stopped.')
    if page['items']:
        version_id = quote(required(field(page['items'][0], 'id'), 'version ID'), safe='')
        api.request('GET', f'{path}/versions/{version_id}')

    html = api.request('GET', path + '/renders/html', binary=True)
    files.save('report.html', html)
    return {
        'scenario': '04',
        'versions': len(page['items']),
        'hasMore': page['hasMore'],
        'exportFile': str(files.directory / 'report.html'),
    }


def share_report(api, files, state):
    """05: Create a private 30-day access link only on an explicit request."""
    files.refuse_existing('share.json')
    path = mapped_path(state, 'document') + '/shares'
    body = {'expiresInDays': 30}
    files.pending('05', api, path, body)
    result = api.request('POST', path, body)
    # Retain the response even if malformed: a link may already exist remotely.
    files.save('share.json', result)
    share_id = required(field(result.get('share'), 'id'), 'valid share ID')
    required(field(result.get('share'), 'url'), 'valid share URL')
    files.done('05')
    return {
        'scenario': '05',
        'shareId': share_id,
        'shareFile': str(files.directory / 'share.json'),
    }


def register_webhook(api, files, state):
    """06: Register lifecycle events with an authorized owner/admin credential."""
    files.refuse_existing('webhook.json')
    callback = required(os.environ.get('MDLOGIC_WEBHOOK_URL'), 'MDLOGIC_WEBHOOK_URL')
    url = urlsplit(callback)
    if (
        url.scheme != 'https'
        or not url.hostname
        or url.username
        or url.password
        or url.fragment
    ):
        raise ExampleError('Use an explicit public HTTPS webhook URL without userinfo or fragment.')

    catalogue = api.request('GET', '/api/v1/webhooks/events')
    if not isinstance(catalogue.get('events'), list) or not all(
        event in catalogue['events'] for event in EVENTS
    ):
        raise ExampleError('The live event catalogue does not support all requested events.')

    path = team_path() + '/webhooks'
    body = {'url': callback, 'events': EVENTS, 'description': 'Generated report lifecycle'}
    files.pending('06', api, path, body)
    result = api.request('POST', path, body)
    # The signing secret is returned once. Store it privately and never print it.
    files.save('webhook.json', result)
    webhook_id = required(field(result.get('webhook'), 'id'), 'valid webhook ID')
    required(result.get('secret'), 'once-only signing secret')
    files.done('06')
    return {
        'scenario': '06',
        'webhookId': webhook_id,
        'secretFile': str(files.directory / 'webhook.json'),
    }


SCENARIOS = {
    '01': create_project,
    '02': create_report,
    '03': update_report,
    '04': export_report,
    '05': share_report,
    '06': register_webhook,
}
