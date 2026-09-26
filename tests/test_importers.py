"""Markdown and RESULT.json importers write through the core Library API."""
from __future__ import annotations

import json
import os
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
    global Library, import_markdown, import_result, capture_result
    from agentbrain_contextlib.capture import capture_result
    from agentbrain_contextlib.importers import import_markdown, import_result
    from agentbrain_contextlib.library import Library

WHEN = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _lib(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / 'lib'
    lib = Library.init(root, clock=lambda: WHEN, writer='cli')
    lib.create_project('harbor', 'Harbor', purpose='Importer test.', owners=('mara',))
    return lib, Path(tmp.name)


class TestImportMarkdown(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_first_heading_is_the_title(self):
        lib, tmp = _lib(self)
        path = tmp / 'fog.md'
        path.write_text(
            '# Offline forms beat networked fog logs\n'
            '\n'
            '**Lesson:** write the form on paper first.\n',
            encoding='utf-8',
        )
        result = import_markdown(lib, 'harbor', path, 'lesson', 'mara')
        self.assertIn('id', result)
        self.assertIn('path', result)
        self.assertIn('status', result)
        got = lib.get('harbor', result['id'])
        self.assertEqual(got['meta']['title'], 'Offline forms beat networked fog logs')
        self.assertEqual(got['meta']['type'], 'lesson')
        self.assertEqual(got['meta']['author'], 'mara')
        self.assertIn('write the form on paper first', got['body'])
        self.assertNotIn('# Offline forms', got['body'])

    def test_heading_need_not_be_the_first_line(self):
        lib, tmp = _lib(self)
        path = tmp / 'note.md'
        path.write_text(
            'intro paragraph\n'
            '# Character\n'
            'Fl W 15s is the lamp pattern.\n',
            encoding='utf-8',
        )
        result = import_markdown(lib, 'harbor', path, 'glossary', 'mara')
        got = lib.get('harbor', result['id'])
        self.assertEqual(got['meta']['title'], 'Character')
        self.assertIn('Fl W 15s', got['body'])
        self.assertNotIn('intro paragraph', got['body'])

    def test_stem_when_there_is_no_heading(self):
        lib, tmp = _lib(self)
        path = tmp / 'tide-range.md'
        path.write_text('Mean tidal range at the headland is 3.2 metres.\n', encoding='utf-8')
        result = import_markdown(lib, 'harbor', path, 'fact', 'guest')
        got = lib.get('harbor', result['id'])
        self.assertEqual(got['meta']['title'], 'tide-range')
        self.assertIn('3.2 metres', got['body'])
        self.assertEqual(result['status'], 'proposed')

    def test_missing_file(self):
        lib, tmp = _lib(self)
        with self.assertRaises(ValueError) as raised:
            import_markdown(lib, 'harbor', tmp / 'missing.md', 'fact', 'mara')
        self.assertIn('not found', str(raised.exception))

    def test_expands_user_home(self):
        lib, tmp = _lib(self)
        home = tmp / 'home'
        home.mkdir()
        path = home / 'fog.md'
        path.write_text(
            '# Offline forms beat networked fog logs\n'
            '\n'
            '**Lesson:** write the form on paper first.\n',
            encoding='utf-8',
        )
        old = os.environ.get('HOME')
        os.environ['HOME'] = str(home)
        try:
            result = import_markdown(lib, 'harbor', '~/fog.md', 'lesson', 'mara')
        finally:
            if old is None:
                os.environ.pop('HOME', None)
            else:
                os.environ['HOME'] = old
        got = lib.get('harbor', result['id'])
        self.assertEqual(got['meta']['title'], 'Offline forms beat networked fog logs')

    def test_refuses_a_secret(self):
        lib, tmp = _lib(self)
        path = tmp / 'leaky.md'
        path.write_text('# Leaky\n\npassword: hunter2\n', encoding='utf-8')
        with self.assertRaises(ValueError) as raised:
            import_markdown(lib, 'harbor', path, 'fact', 'mara')
        self.assertIn('secret', str(raised.exception).lower())


class TestImportResult(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_wraps_capture_result(self):
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
        via_importer = import_result(lib, 'harbor', path, author='service:capture')
        self.assertIn('return_id', via_importer)
        self.assertEqual(len(via_importer['proposed_ids']), 1)
        got = lib.get('harbor', via_importer['return_id'])
        self.assertEqual(got['meta']['type'], 'return')
        self.assertEqual(got['meta']['status'], 'current')
        self.assertIn('Lamp status stayed current', got['body'])
        lesson = lib.get('harbor', via_importer['proposed_ids'][0])
        self.assertEqual(lesson['meta']['status'], 'proposed')
        again = capture_result(lib, 'harbor', path, author='service:capture')
        self.assertEqual(again['return_id'], via_importer['return_id'])
        self.assertEqual(again['proposed_ids'], via_importer['proposed_ids'])

    def test_missing_result_file(self):
        lib, tmp = _lib(self)
        with self.assertRaises(ValueError):
            import_result(lib, 'harbor', tmp / 'nope.json')

    def test_expands_user_home(self):
        lib, tmp = _lib(self)
        home = tmp / 'home'
        home.mkdir()
        path = home / 'RESULT.json'
        path.write_text(json.dumps({
            'title': 'Keeper trial',
            'userOutcome': 'Lamp status stayed current',
        }), encoding='utf-8')
        old = os.environ.get('HOME')
        os.environ['HOME'] = str(home)
        try:
            result = import_result(lib, 'harbor', '~/RESULT.json')
        finally:
            if old is None:
                os.environ.pop('HOME', None)
            else:
                os.environ['HOME'] = old
        self.assertIn('return_id', result)
        got = lib.get('harbor', result['return_id'])
        self.assertEqual(got['meta']['type'], 'return')
        self.assertIn('Lamp status stayed current', got['body'])


if __name__ == '__main__':
    unittest.main()
