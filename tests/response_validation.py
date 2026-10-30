#!/usr/bin/env python3
"""Response validation and source-preservation checks using synthetic loopback services."""

import json
import pathlib
import shutil
import sys
import unittest

import verify as contract


class EdgeMock(contract.Mock):
    def route(self):
        mode = self.server.mode
        path = self.path.split('?')[0]
        response = None
        status = 200
        headers = {}
        if mode == 'numeric-project' and self.command == 'POST' and path.endswith('/projects'):
            response = {'project': {'id': 123}}
            status = 201
        elif mode == 'empty-create-revision' and self.command == 'POST' and path.endswith('/artifacts'):
            response = {'artifact': {'id': 'doc-1', 'revision': ''}, 'decision': 'create'}
            status = 201
        elif mode == 'empty-live-revision' and self.command == 'GET' and path.endswith('/doc-1'):
            response = {'document': {'id': 'doc-1', 'revision': '', 'content': '# Before'}}
        elif mode == 'empty-update-revision' and self.command == 'PUT':
            response = {'document': {'id': 'doc-1', 'revision': ''}}
        elif mode == 'malformed-history' and path.endswith('/versions'):
            response = {}
        elif mode == 'numeric-history-id' and path.endswith('/versions'):
            response = {'items': [{'id': 123}], 'hasMore': False}
        elif mode == 'invalid-catalogue' and path == '/api/v1/webhooks/events':
            response = {'events': {'document.created': True}}
        elif mode == 'wrong-error-types' and self.command == 'GET' and path.endswith('/doc-1'):
            status = 401
            response = {'code': [contract.TOKEN], 'details': {'reason': [contract.TOKEN]}}
        elif mode == 'huge-retry' and self.command == 'GET' and path.endswith('/doc-1'):
            status = 429
            response = {'code': 'RATE_LIMITED'}
            headers = {'Retry-After': '9' * 5000}
        elif mode == 'curlrc-retry' and self.command == 'POST':
            status = 503
            response = {'code': 'UNAVAILABLE'}
        elif mode == 'crlf' and self.command == 'POST' and path.endswith('/artifacts'):
            response = {
                'artifact': {'id': 'doc-1', 'revision': 'crlf-revision'},
                'decision': 'create',
            }
            status = 201
        if response is None:
            return super().route()
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.calls.append((self.command, self.path, raw, dict(self.headers)))
        self.reply(status, response, headers)


class ResponseValidationTests(unittest.TestCase):
    def setUp(self):
        self.case = contract.ContractTests()
        self.case.setUp()
        self.case.server.RequestHandlerClass = EdgeMock

    def tearDown(self):
        self.case.tearDown()

    def test_response_validation_and_source_preservation(self):
        c = self.case
        for language in contract.SELECTED:
            if language == 'csharp' and not shutil.which('dotnet'):
                continue
            with self.subTest(language=language):
                for mode, scenario in [
                    ('numeric-project', '01'),
                    ('empty-create-revision', '02'),
                    ('empty-live-revision', '03'),
                    ('empty-update-revision', '03'),
                    ('malformed-history', '04'),
                    ('numeric-history-id', '04'),
                    ('invalid-catalogue', '06'),
                    ('wrong-error-types', '03'),
                    ('huge-retry', '03'),
                ]:
                    directory = c.prepare(language + '-' + mode)
                    if scenario == '02':
                        (directory / 'state.json').write_text(json.dumps({'projectId': 'project-1'}))
                    elif scenario != '01':
                        c.seed(directory)
                    c.server.mode = mode
                    c.server.calls = []
                    c.run_example(language, scenario, False)
                    if scenario in ('01', '02'):
                        self.assertTrue((directory / ('pending-' + scenario + '.json')).exists())
                    if mode == 'empty-live-revision':
                        self.assertFalse(any(row[0] == 'PUT' for row in c.server.calls))
                    if mode == 'empty-update-revision':
                        self.assertEqual(
                            json.loads((directory / 'state.json').read_text())['revision'],
                            'opaque-rev-1',
                        )
                    if mode in ('malformed-history', 'numeric-history-id'):
                        self.assertFalse((directory / 'report.html').exists())
                    if mode == 'numeric-history-id':
                        self.assertFalse(any('/versions/123' in row[1] for row in c.server.calls))
                    if mode == 'invalid-catalogue':
                        self.assertFalse(any(row[0] == 'POST' for row in c.server.calls))
                    if mode == 'huge-retry':
                        self.assertEqual(sum(row[0] == 'GET' for row in c.server.calls), 1)
                for index, value in enumerate([None, [], 'damaged mapping']):
                    directory = c.prepare(language + '-mapping-' + str(index))
                    (directory / 'state.json').write_text(json.dumps(value))
                    c.server.mode = 'ok'
                    c.server.calls = []
                    c.run_example(language, '01', False)
                    self.assertFalse(
                        c.server.calls,
                        'Invalid saved state must stop before API calls',
                    )
                directory = c.prepare(language + '-crlf')
                (directory / 'state.json').write_text(json.dumps({'projectId': 'project-1'}))
                source = directory / 'report.md'
                raw = b'# Report\r\n\r\nSynthetic only.\r\n'
                source.write_bytes(raw)
                c.env['MDLOGIC_INPUT'] = str(source)
                c.server.mode = 'crlf'
                c.server.calls = []
                c.run_example(language, '02')
                body = json.loads(next(row[2] for row in c.server.calls if row[0] == 'POST'))
                self.assertEqual(body['content'].encode(), raw)
                self.assertEqual(source.read_bytes(), raw)
                del c.env['MDLOGIC_INPUT']
                if language == 'shell':
                    directory = c.prepare('shell-curlrc')
                    config = directory / 'curl-config'
                    config.mkdir()
                    (config / '.curlrc').write_text('retry=2\nretry-delay=1\n')
                    c.env['CURL_HOME'] = str(config)
                    c.server.mode = 'curlrc-retry'
                    c.server.calls = []
                    c.run_example(language, '01', False)
                    self.assertEqual(sum(row[0] == 'POST' for row in c.server.calls), 1)
                    del c.env['CURL_HOME']
                print(
                    'PASS ' + language
                    + ': typed fields/revisions, mapping/history/catalogue validation, '
                    'safe logs, huge throttles, CRLF'
                    + (', curlrc isolation' if language == 'shell' else ''),
                    flush=True,
                )


if __name__ == '__main__':
    unittest.main(verbosity=2)
