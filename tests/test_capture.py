"""RESULT.json becomes a return, and lessons land in the inbox."""
from __future__ import annotations

import hashlib
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
    global capture_result, Library
    from agentbrain_contextlib.capture import capture_result
    from agentbrain_contextlib.library import Library

WHEN = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _lib(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / 'lib'
    lib = Library.init(root, clock=lambda: WHEN, writer='cli')
    lib.create_project('harbor', 'Harbor', purpose='Capture test.', owners=('mara',))
    return lib, Path(tmp.name)


class TestCapture(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_outcome_fields_and_proposed_lessons(self):
        lib, tmp = _lib(self)
        payload = {
            'title': 'Keeper trial',
            'userOutcome': 'Lamp status stayed current',
            'remainingGaps': 'Fog form is still network-first',
            'nextActor': 'keepers',
            'lessons': ['Offline forms get filled when the hut link drops'],
        }
        path = tmp / 'RESULT.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        result = capture_result(lib, 'harbor', path)
        self.assertIn('return_id', result)
        self.assertEqual(len(result['proposed_ids']), 1)
        got = lib.get('harbor', result['return_id'])
        self.assertEqual(got['meta']['type'], 'return')
        self.assertEqual(got['meta']['status'], 'current')
        self.assertEqual(got['meta']['author'], 'service:capture')
        self.assertIn('Lamp status stayed current', got['body'])
        self.assertIn('Fog form is still network-first', got['body'])
        self.assertIn('keepers', got['body'])
        self.assertTrue(got['path'].startswith('returns/'))
        evidence = got['evidence']
        self.assertEqual(evidence[0]['state'], 'ok')
        self.assertEqual(evidence[0]['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(evidence[0]['ref'].startswith('project:exports/capture-'))
        lesson = lib.get('harbor', result['proposed_ids'][0])
        self.assertEqual(lesson['meta']['type'], 'lesson')
        self.assertEqual(lesson['meta']['status'], 'proposed')
        self.assertTrue(lesson['path'].startswith('inbox/'))
        self.assertIn('Offline forms', lesson['body'])
        again = capture_result(lib, 'harbor', path)
        self.assertEqual(again['return_id'], result['return_id'])
        self.assertEqual(again['proposed_ids'], result['proposed_ids'])

    def test_summary_fallback(self):
        lib, tmp = _lib(self)
        path = tmp / 'RESULT.json'
        path.write_text(json.dumps({'summary': 'Watch completed from the local clone.'}), encoding='utf-8')
        result = capture_result(lib, 'harbor', path, author='service:capture')
        body = lib.get('harbor', result['return_id'])['body']
        self.assertIn('Watch completed from the local clone.', body)
        self.assertNotIn('**User outcome:**', body)
        self.assertEqual(result['proposed_ids'], [])


if __name__ == '__main__':
    unittest.main()
