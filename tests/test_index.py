"""The search index rebuilds from files and nowhere else."""
from __future__ import annotations

import sqlite3
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
    global Index, Library
    from agentbrain_contextlib.index import Index
    from agentbrain_contextlib.library import Library

WHEN = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _lib(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / 'lib'
    lib = Library.init(root, clock=lambda: WHEN, writer='cli')
    lib.create_project('harbor', 'Harbor', purpose='Index test.', owners=('mara',))
    return lib


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_search_is_empty_until_rebuild(self):
        lib = _lib(self)
        rec = lib.record(
            'harbor', 'fact', 'Lamp character', '**Fact:** Fl W 15s.\n',
            author='mara', evidence=('note:log',),
        )
        index = Index(lib)
        self.assertEqual(index.search('harbor', 'lamp'), [])
        count = index.rebuild('harbor')
        self.assertEqual(count, 1)
        found = index.search('harbor', 'lamp')
        self.assertEqual([item['id'] for item in found], [rec['id']])
        self.assertEqual(found[0]['type'], 'fact')
        self.assertIn('lamp', found[0]['snippet'].lower())
        self.assertIn('id', found[0])
        self.assertIn('path', found[0])
        self.assertIn('date', found[0])

    def test_rebuild_matches_files_only(self):
        lib = _lib(self)
        alpha = lib.record(
            'harbor', 'decision', 'Alpha lamp', '**Decision:** keeper logs.\n',
            author='mara', evidence=('note:a',),
        )
        beta = lib.record(
            'harbor', 'fact', 'Beta tide', '**Fact:** 3.2 metres.\n',
            author='mara', evidence=('note:b',),
        )
        index = Index(lib)
        self.assertEqual(index.rebuild(), 2)
        db = lib.project_dir('harbor') / '.contextlib' / 'index.sqlite'
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                'INSERT INTO records (id, type, title, status, created, path, body) VALUES (?, ?, ?, ?, ?, ?, ?)',
                ('fake-id', 'fact', 'Fake lamp', 'current', '2026-01-01T00:00:00Z', 'facts/fake.md', 'lamp'),
            )
            conn.commit()
        finally:
            conn.close()
        fake_ids = [item['id'] for item in index.search('harbor', 'lamp')]
        self.assertIn('fake-id', fake_ids)
        gamma = lib.record(
            'harbor', 'fact', 'Gamma lamp', '**Fact:** still the lamp.\n',
            author='mara', evidence=('note:c',),
        )
        stale = [item['id'] for item in index.search('harbor', 'lamp')]
        self.assertNotIn(gamma['id'], stale)
        (lib.project_dir('harbor') / alpha['path']).unlink()
        self.assertIn(alpha['id'], [item['id'] for item in index.search('harbor', 'lamp')])
        count = index.rebuild('harbor')
        self.assertEqual(count, 2)
        found = [item['id'] for item in index.search('harbor', 'lamp')]
        self.assertIn(gamma['id'], found)
        self.assertNotIn(alpha['id'], found)
        self.assertNotIn('fake-id', found)
        self.assertNotIn(beta['id'], found)

    def test_title_outranks_body_and_filters_apply(self):
        lib = _lib(self)
        title_hit = lib.record(
            'harbor', 'decision', 'Lamp policy', '**Decision:** unrelated words.\n',
            author='mara', evidence=('note:t',),
        )
        body_hit = lib.record(
            'harbor', 'fact', 'Tide table', '**Fact:** the lamp is listed here.\n',
            author='mara', evidence=('note:b',),
        )
        old = lib.record(
            'harbor', 'decision', 'Old lamp rule', '**Decision:** poll.\n',
            author='mara', evidence=('note:o',),
        )
        lib.supersede('harbor', old['id'], title_hit['id'], 'replaced', author='mara')
        index = Index(lib)
        index.rebuild('harbor')
        ranked = index.search('harbor', 'lamp')
        self.assertEqual(ranked[0]['id'], title_hit['id'])
        self.assertIn(body_hit['id'], [item['id'] for item in ranked])
        self.assertNotIn(old['id'], [item['id'] for item in ranked])
        superseded = index.search('harbor', 'lamp', status='superseded')
        self.assertEqual([item['id'] for item in superseded], [old['id']])
        facts = index.search('harbor', 'lamp', type_='fact')
        self.assertEqual([item['id'] for item in facts], [body_hit['id']])
        self.assertEqual(len(index.search('harbor', 'lamp', limit=1)), 1)


if __name__ == '__main__':
    unittest.main()
