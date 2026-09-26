"""Brief stays within 8192 bytes, including a 500-record project."""
from __future__ import annotations

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
    global build_brief, Library
    from agentbrain_contextlib.brief import build_brief
    from agentbrain_contextlib.library import Library

WHEN = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _lib(case, purpose):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / 'lib'
    lib = Library.init(root, clock=lambda: WHEN, writer='cli')
    lib.create_project('harbor', 'Harbor Board', purpose=purpose, owners=('mara',))
    return lib


class TestBrief(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_sections_and_due_count(self):
        purpose = 'Harbor dashboard for a fictional headland light.'
        lib = _lib(self, purpose)
        lib.record(
            'harbor', 'decision', 'Use keeper logs',
            '**Decision:** Lamp status comes from keeper logs.\n',
            author='mara', evidence=('note:log',),
        )
        lib.record(
            'harbor', 'requirement', 'Show the character',
            '**Requirement:** the board shows Fl W 15s.\n',
            author='mara', evidence=('note:wall',),
        )
        lib.record(
            'harbor', 'fact', 'Lamp character is Fl W 15s',
            '**Fact:** a white flash every 15 seconds.\n',
            author='mara', evidence=('note:light list',), review_by='2026-09-20',
        )
        lib.record(
            'harbor', 'return', 'Keeper trial',
            '**Return:** the lamp stayed current.\n',
            author='mara', evidence=('note:trial',),
        )
        text = build_brief(lib, 'harbor')
        self.assertLessEqual(len(text.encode('utf-8')), 8192)
        self.assertIn(purpose, text)
        self.assertIn('Current decisions', text)
        self.assertIn('Open requirements', text)
        self.assertIn('Key facts', text)
        self.assertIn('Recent returns', text)
        self.assertIn('Use keeper logs', text)
        self.assertIn('Review due', text)
        self.assertIn('Generated', text)
        self.assertIn('1 record due on or before 2026-09-26.', text)
        sizes = lib.regenerate('harbor')
        brief_path = lib.project_dir('harbor') / 'BRIEF.md'
        self.assertLessEqual(brief_path.stat().st_size, 8192)
        self.assertLessEqual(sizes['projects/harbor/BRIEF.md'], 8192)
        self.assertIn('INDEX.md', sizes)

    def test_five_hundred_records_stay_within_8192(self):
        purpose = 'Size guard for the always-loaded summary.'
        lib = _lib(self, purpose)
        filler = 'lamp ' * 40
        for index in range(500):
            lib.record(
                'harbor', 'fact', 'Synthetic fact %d' % index,
                '**Fact:** %s record %d.\n' % (filler, index),
                author='guest', evidence=('note:synthetic %d' % index,),
            )
        text = build_brief(lib, 'harbor')
        raw = text.encode('utf-8')
        self.assertLessEqual(len(raw), 8192)
        self.assertIn(purpose, text)
        self.assertIn('Current decisions', text)
        self.assertIn('Key facts', text)
        self.assertIn('Review due', text)
        self.assertIn('Generated', text)
        self.assertIn('more', text)
        self.assertLess(text.count('\n- '), 40)
        self.assertNotIn(filler * 2, text)


if __name__ == '__main__':
    unittest.main()
