"""MCP server: newline-delimited JSON-RPC, context_* tools, fixed identity."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


def _unload():
    for key in list(sys.modules):
        if key == 'agentbrain_contextlib' or key.startswith('agentbrain_contextlib.'):
            del sys.modules[key]


def _bind():
    global Library, handle, serve
    from agentbrain_contextlib.library import Library
    from agentbrain_contextlib.mcp import handle, serve

WHEN = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
IDENTITY = 'claude:lighthouse'
TOOLS = (
    'context_brief',
    'context_search',
    'context_get',
    'context_record',
    'context_supersede',
    'context_review_due',
    'context_review',
    'context_capture',
    'context_export',
    'context_import',
    'context_status',
)


def _clock():
    return WHEN


def _open(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / 'lib'
    lib = Library.init(root, clock=_clock, writer='mcp')
    lib.create_project('harbor', 'Harbor', purpose='A fictional headland board.', owners=(IDENTITY,))
    return lib, Path(tmp.name)


def _req(method, params=None, id_=1):
    message = {'jsonrpc': '2.0', 'id': id_, 'method': method}
    if params is not None:
        message['params'] = params
    return message


def _call(lib, name, arguments, identity=IDENTITY, id_=1):
    return handle(lib, identity, _req('tools/call', {'name': name, 'arguments': arguments}, id_=id_))


def _text(response):
    return response['result']['content'][0]['text']


def _payload(response):
    return json.loads(_text(response))


class TestMcp(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_initialize_negotiates_supported_versions(self):
        lib, _tmp = _open(self)
        for version in ('2024-11-05', '2025-03-26', '2025-06-18'):
            response = handle(lib, IDENTITY, _req('initialize', {
                'protocolVersion': version,
                'capabilities': {},
                'clientInfo': {'name': 'test', 'version': '0'},
            }))
            self.assertEqual(response['jsonrpc'], '2.0')
            self.assertEqual(response['result']['protocolVersion'], version)
            self.assertEqual(response['result']['serverInfo']['name'], 'contextlib')
            self.assertIn('tools', response['result']['capabilities'])
        fallback = handle(lib, IDENTITY, _req('initialize', {'protocolVersion': '1999-01-01'}))
        self.assertIn(fallback['result']['protocolVersion'], ('2024-11-05', '2025-03-26', '2025-06-18'))

    def test_notification_returns_none(self):
        lib, _tmp = _open(self)
        self.assertIsNone(handle(lib, IDENTITY, {
            'jsonrpc': '2.0',
            'method': 'notifications/initialized',
        }))
        self.assertIsNone(handle(lib, IDENTITY, {
            'jsonrpc': '2.0',
            'method': 'notifications/cancelled',
        }))
        with_id = handle(lib, IDENTITY, _req('notifications/initialized'))
        self.assertEqual(with_id['jsonrpc'], '2.0')
        self.assertEqual(with_id['id'], 1)
        self.assertIn('result', with_id)

    def test_tools_list_has_every_context_tool(self):
        lib, _tmp = _open(self)
        response = handle(lib, IDENTITY, _req('tools/list'))
        names = [item['name'] for item in response['result']['tools']]
        for name in TOOLS:
            self.assertIn(name, names)
        self.assertEqual(len(names), len(set(names)))
        for item in response['result']['tools']:
            self.assertTrue(item['name'].startswith('context_'))
            self.assertIn('inputSchema', item)
            self.assertIn('description', item)

    def test_record_get_brief_search_status(self):
        lib, _tmp = _open(self)
        created = _call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'decision',
            'title': 'Use keeper logs',
            'body': '**Decision:** the lamp is what the keeper signed.\n',
            'evidence': ['note:keeper log'],
            'tags': ['lamp'],
        })
        self.assertFalse(created['result']['isError'], _text(created))
        rec = _payload(created)
        self.assertEqual(rec['status'], 'current')
        got = _call(lib, 'context_get', {'project': 'harbor', 'id': rec['id']})
        self.assertFalse(got['result']['isError'], _text(got))
        body = _payload(got)
        self.assertEqual(body['meta']['author'], IDENTITY)
        self.assertEqual(body['meta']['title'], 'Use keeper logs')
        self.assertIn('keeper signed', body['body'])
        self.assertIn('supersession_chain', body)
        brief = _call(lib, 'context_brief', {'project': 'harbor'})
        self.assertFalse(brief['result']['isError'])
        self.assertIn('Use keeper logs', _text(brief))
        self.assertLessEqual(len(_text(brief).encode('utf-8')), 8192)
        found = _call(lib, 'context_search', {'project': 'harbor', 'query': 'keeper'})
        self.assertFalse(found['result']['isError'], _text(found))
        hits = _payload(found)
        self.assertEqual(hits[0]['id'], rec['id'])
        status = _call(lib, 'context_status', {'project': 'harbor'})
        self.assertFalse(status['result']['isError'])
        info = _payload(status)
        self.assertEqual(info['identity'], IDENTITY)
        self.assertEqual(info['project']['slug'], 'harbor')
        self.assertGreaterEqual(info['project']['counts']['current'], 1)
        self.assertIn('inbox', info['project'])
        self.assertIn('review_due', info['project'])
        self.assertIn('index_age_seconds', info['project'])

    def test_identity_is_fixed_and_author_argument_is_ignored(self):
        lib, _tmp = _open(self)
        created = _call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'fact',
            'title': 'Lamp character is Fl W 15s',
            'body': '**Fact:** a white flash every 15 seconds.\n',
            'evidence': ['note:log'],
            'author': 'attacker:impersonate',
        })
        self.assertFalse(created['result']['isError'], _text(created))
        rec = _payload(created)
        got = lib.get('harbor', rec['id'])
        self.assertEqual(got['meta']['author'], IDENTITY)
        self.assertNotEqual(got['meta']['author'], 'attacker:impersonate')

    def test_inbox_rules_ignore_client_status(self):
        lib, _tmp = _open(self)
        outsider = 'codex:guest'
        forced = _call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'decision',
            'title': 'Guests wait in the inbox',
            'body': '**Decision:** a guest cannot skip review.\n',
            'evidence': ['note:guest'],
            'status': 'current',
            'author': 'mara',
        }, identity=outsider)
        self.assertFalse(forced['result']['isError'], _text(forced))
        rec = _payload(forced)
        self.assertEqual(rec['status'], 'proposed')
        self.assertTrue(rec['path'].startswith('inbox/'), rec['path'])
        got = lib.get('harbor', rec['id'])
        self.assertEqual(got['meta']['author'], outsider)
        self.assertEqual(got['meta']['status'], 'proposed')
        fact = _call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'fact',
            'title': 'Guest fact with evidence',
            'body': '**Fact:** evidence still makes a fact current.\n',
            'evidence': ['note:log'],
            'status': 'proposed',
        }, identity=outsider)
        self.assertFalse(fact['result']['isError'], _text(fact))
        self.assertEqual(_payload(fact)['status'], 'current')

    def test_supersede_review_due_and_review(self):
        lib, _tmp = _open(self)
        old = _payload(_call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'decision',
            'title': 'Poll AIS',
            'body': '**Decision:** poll AIS.\n',
            'evidence': ['note:early'],
        }))
        new = _payload(_call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'decision',
            'title': 'Use keeper logs',
            'body': '**Decision:** logs.\n',
            'evidence': ['note:log'],
        }))
        moved = _call(lib, 'context_supersede', {
            'project': 'harbor',
            'old_id': old['id'],
            'new_id': new['id'],
            'reason': 'AIS is traffic, not lamp status',
            'author': 'someone-else',
        })
        self.assertFalse(moved['result']['isError'], _text(moved))
        self.assertEqual(_payload(moved)['status'], 'superseded')
        after = lib.get('harbor', old['id'])
        self.assertEqual(after['meta']['status'], 'superseded')
        self.assertEqual(after['meta']['author'], IDENTITY)
        due_fact = _payload(_call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'fact',
            'title': 'Due fact',
            'body': '**Fact:** due.\n',
            'evidence': ['note:due'],
            'review_by': '2026-09-26',
        }))
        later = _payload(_call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'fact',
            'title': 'Later fact',
            'body': '**Fact:** later.\n',
            'evidence': ['note:later'],
            'review_by': '2026-12-01',
        }))
        due = _payload(_call(lib, 'context_review_due', {'project': 'harbor'}))
        ids = [item['id'] for item in due]
        self.assertIn(due_fact['id'], ids)
        self.assertNotIn(later['id'], ids)
        reviewed = _call(lib, 'context_review', {
            'project': 'harbor',
            'id': new['id'],
            'outcome': 'confirm',
            'note': 'still right',
            'next_review_by': '2027-01-15',
            'author': 'intruder',
        })
        self.assertFalse(reviewed['result']['isError'], _text(reviewed))
        self.assertEqual(lib.get('harbor', new['id'])['meta']['review_by'], '2027-01-15')

    def test_capture_export_import(self):
        lib, tmp = _open(self)
        result_path = tmp / 'RESULT.json'
        result_path.write_bytes(json.dumps({
            'title': 'Keeper trial',
            'userOutcome': 'Lamp status stayed current',
            'remainingGaps': 'Fog form is still network-first',
            'nextActor': 'keepers',
            'lessons': ['Offline forms get filled when the hut link drops'],
        }).encode('utf-8'))
        captured = _call(lib, 'context_capture', {
            'project': 'harbor',
            'path': str(result_path),
            'author': 'service:other',
        })
        self.assertFalse(captured['result']['isError'], _text(captured))
        data = _payload(captured)
        self.assertIn('return_id', data)
        got = lib.get('harbor', data['return_id'])
        self.assertEqual(got['meta']['author'], IDENTITY)
        self.assertEqual(got['meta']['type'], 'return')
        out = tmp / 'export'
        exported = _call(lib, 'context_export', {
            'project': 'harbor',
            'out_dir': str(out),
        })
        self.assertFalse(exported['result']['isError'], _text(exported))
        bundle = _payload(exported)
        self.assertTrue(Path(bundle['path']).is_file())
        self.assertGreaterEqual(bundle['records'], 1)
        imported = _call(lib, 'context_import', {'path': bundle['path']})
        self.assertFalse(imported['result']['isError'], _text(imported))
        info = _payload(imported)
        self.assertEqual(info['project'], 'harbor')
        self.assertEqual(info['conflicts'], [])

    def test_errors_are_iserror_results(self):
        lib, _tmp = _open(self)
        missing = _call(lib, 'context_get', {'project': 'harbor', 'id': 'dec-20260926-0000'})
        self.assertTrue(missing['result']['isError'])
        self.assertIn('no record', _text(missing).lower())
        unknown = _call(lib, 'context_not_a_tool', {'project': 'harbor'})
        self.assertTrue(unknown['result']['isError'])
        secret = 'sk' + '-' + 'Abcd1234'
        refused = _call(lib, 'context_record', {
            'project': 'harbor',
            'type': 'fact',
            'title': 'Bad token',
            'body': '**Fact:** ' + secret + '\n',
            'evidence': ['note:no'],
        })
        self.assertTrue(refused['result']['isError'])
        self.assertIn('secret', _text(refused).lower())
        self.assertNotIn(secret, _text(refused))
        method = handle(lib, IDENTITY, _req('no/such/method'))
        self.assertIn('error', method)
        self.assertEqual(method['error']['code'], -32601)

    def test_serve_newline_delimited_jsonrpc(self):
        lib, _tmp = _open(self)
        messages = [
            _req('initialize', {'protocolVersion': '2025-03-26'}, id_=1),
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            _req('tools/list', id_=2),
            _req('tools/call', {
                'name': 'context_status',
                'arguments': {'project': 'harbor'},
            }, id_=3),
            _req('tools/call', {
                'name': 'context_record',
                'arguments': {
                    'project': 'harbor',
                    'type': 'lesson',
                    'title': 'Offline forms win',
                    'body': '**Lesson:** write local first.\n',
                    'evidence': ['note:fog'],
                    'author': 'other-identity',
                },
            }, id_=4),
        ]
        stdin = io.StringIO(''.join(json.dumps(item) + '\n' for item in messages))
        stdout = io.StringIO()
        code = serve(lib, IDENTITY, stdin=stdin, stdout=stdout)
        self.assertEqual(code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 4)
        init, listed, status, created = [json.loads(line) for line in lines]
        self.assertEqual(init['result']['protocolVersion'], '2025-03-26')
        names = [item['name'] for item in listed['result']['tools']]
        for name in TOOLS:
            self.assertIn(name, names)
        self.assertFalse(status['result']['isError'])
        self.assertFalse(created['result']['isError'])
        rec = json.loads(created['result']['content'][0]['text'])
        self.assertEqual(lib.get('harbor', rec['id'])['meta']['author'], IDENTITY)
        parse_in = io.StringIO('{not json\n')
        parse_out = io.StringIO()
        self.assertEqual(serve(lib, IDENTITY, stdin=parse_in, stdout=parse_out), 0)
        err = json.loads(parse_out.getvalue().splitlines()[0])
        self.assertEqual(err['error']['code'], -32700)


class TestMcpApprovalClaims(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_agent_supplied_approval_waits_in_the_inbox(self):
        lib, _tmp = _open(self)
        response = _call(lib, 'context_record', {
            'project': 'harbor', 'type': 'decision', 'title': 'Claimed approval',
            'body': '**Decision:** skip review.', 'approved_by': 'the owner said yes',
        }, identity='codex:not-an-owner')
        self.assertFalse(response['result']['isError'])
        made = _payload(response)
        self.assertEqual(made['status'], 'proposed')
        stored = lib.get('harbor', made['id'])['meta']
        self.assertEqual(stored['author'], 'codex:not-an-owner')
        self.assertEqual(stored['approved_by'], 'the owner said yes')

    def test_owner_approval_still_lands_current(self):
        lib, _tmp = _open(self)
        made = _payload(_call(lib, 'context_record', {
            'project': 'harbor', 'type': 'decision', 'title': 'Owner decision',
            'body': '**Decision:** ship it.', 'approved_by': 'owner',
        }))
        self.assertEqual(made['status'], 'current')
