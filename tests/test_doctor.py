"""Doctor: sample library passes; each ten-minute rule fails on a crafted library."""
from __future__ import annotations

import shutil
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
    global Library, run_doctor
    from agentbrain_contextlib.doctor import run_doctor
    from agentbrain_contextlib.library import Library

WHEN = datetime(2026, 9, 26, 18, 0, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'examples' / 'sample-library'


def _clock():
    return WHEN


def _open(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / 'lib'
    lib = Library.init(root, clock=_clock, writer='cli')
    lib.create_project('harbor', 'Harbor', purpose='A fictional headland board.', owners=('mara',))
    lib.record(
        'harbor', 'fact', 'Lamp character is Fl W 15s',
        '**Fact:** a white flash every 15 seconds.\n',
        author='mara', evidence=('note:keeper log',),
    )
    lib.regenerate('harbor')
    return lib


def _blob(ok_lines):
    return '\n'.join(ok_lines).lower()


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_sample_library_passes_ten_minute(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dest = Path(tmp.name) / 'sample-library'
        shutil.copytree(SAMPLE, dest)
        lib = Library(dest, clock=_clock, writer='cli')
        ok, lines = run_doctor(lib, ten_minute=True)
        self.assertTrue(ok, lines)
        self.assertTrue(any('ten minutes' in line.lower() for line in lines), lines)
        ok_one, lines_one = run_doctor(lib, 'lighthouse-app', ten_minute=True)
        self.assertTrue(ok_one, lines_one)

    def test_missing_readme(self):
        lib = _open(self)
        (lib.project_dir('harbor') / 'README.md').unlink()
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        self.assertIn('readme.md is missing', _blob(lines))

    def test_missing_brief(self):
        lib = _open(self)
        (lib.project_dir('harbor') / 'BRIEF.md').unlink()
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        self.assertIn('brief.md is missing', _blob(lines))

    def test_missing_index(self):
        lib = _open(self)
        (lib.project_dir('harbor') / 'INDEX.md').unlink()
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        self.assertIn('index.md is missing', _blob(lines))

    def test_brief_over_8192_bytes(self):
        lib = _open(self)
        path = lib.project_dir('harbor') / 'BRIEF.md'
        path.write_bytes(
            b'# Harbor\n\n**Generated:** 2026-09-26T18:00:00Z\n\n' + (b'x' * 8200)
        )
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        blob = _blob(lines)
        self.assertIn('brief.md', blob)
        self.assertTrue('8192' in blob or 'bytes' in blob, lines)

    def test_brief_more_than_30_days_old(self):
        lib = _open(self)
        path = lib.project_dir('harbor') / 'BRIEF.md'
        text = path.read_bytes().decode('utf-8')
        text = text.replace('**Generated:** 2026-09-26T12:00:00Z', '**Generated:** 2026-01-01T00:00:00Z')
        if '**Generated:** 2026-01-01T00:00:00Z' not in text:
            text = '# Harbor\n\n**Generated:** 2026-01-01T00:00:00Z\n\nPurpose: board.\n'
        path.write_bytes(text.encode('utf-8'))
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        blob = _blob(lines)
        self.assertIn('brief.md', blob)
        self.assertTrue('days old' in blob, lines)

    def test_current_record_has_no_evidence(self):
        lib = _open(self)
        rec = lib.record(
            'harbor', 'decision', 'Skip the evidence',
            '**Decision:** do not.\n',
            author='mara', evidence=(),
        )
        lib.regenerate('harbor')
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        blob = _blob(lines)
        self.assertIn('evidence', blob)
        self.assertIn(rec['id'], blob)

    def test_current_record_has_no_review_by(self):
        lib = _open(self)
        rec = lib.record(
            'harbor', 'fact', 'Tide without a review date',
            '**Fact:** the tide is local.\n',
            author='mara', evidence=('note:tide table',),
        )
        path = lib.project_dir('harbor') / rec['path']
        text = path.read_bytes().decode('utf-8')
        text = text.replace('review_by: 2026-10-26', 'review_by: null')
        self.assertIn('review_by: null', text)
        path.write_bytes(text.encode('utf-8'))
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        blob = _blob(lines)
        self.assertTrue('review' in blob, lines)
        self.assertIn(rec['id'], blob)

    def test_secret_is_found(self):
        lib = _open(self)
        token = 'sk' + '-' + 'Abcd1234'
        readme = lib.project_dir('harbor') / 'README.md'
        readme.write_bytes((readme.read_bytes().decode('utf-8') + '\n' + token + '\n').encode('utf-8'))
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        blob = _blob(lines)
        self.assertIn('secret', blob)
        self.assertNotIn(token, '\n'.join(lines))

    def test_library_readme_secret_is_found(self):
        lib = _open(self)
        token = 'sk' + '-' + 'Abcd1234'
        readme = Path(lib.root) / 'README.md'
        readme.write_bytes((readme.read_bytes().decode('utf-8') + '\n' + token + '\n').encode('utf-8'))
        ok, lines = run_doctor(lib, ten_minute=True)
        self.assertFalse(ok)
        blob = _blob(lines)
        self.assertIn('secret', blob)
        self.assertNotIn(token, '\n'.join(lines))
        ok_one, lines_one = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok_one)
        self.assertIn('secret', _blob(lines_one))
        self.assertNotIn(token, '\n'.join(lines_one))

    def test_absolute_home_path_is_found(self):
        lib = _open(self)
        home = '/' + 'Users/' + 'ada/notes.txt'
        readme = lib.project_dir('harbor') / 'README.md'
        readme.write_bytes((readme.read_bytes().decode('utf-8') + '\nsee ' + home + '\n').encode('utf-8'))
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        blob = _blob(lines)
        self.assertTrue('home path' in blob or 'absolute' in blob, lines)
        self.assertNotIn(home, '\n'.join(lines))

    def test_index_does_not_rebuild(self):
        lib = _open(self)
        broken = lib.project_dir('harbor') / 'facts' / 'broken.md'
        broken.write_bytes(b'---\nid: fact-20260926-ffff\ntype: fact\ntitle: Broken\n')
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        self.assertIn('rebuild', _blob(lines))

    def test_export_import_hash_change(self):
        lib = _open(self)
        rec = lib.record(
            'harbor', 'fact', 'Pinned tide',
            '**Fact:** original body.\n',
            author='mara', evidence=('note:tide',),
        )
        lib.regenerate('harbor')
        path = lib.project_dir('harbor') / rec['path']
        text = path.read_bytes().decode('utf-8')
        tampered = text.replace('**Fact:** original body.\n', '**Fact:** the body changed.\n')
        self.assertNotEqual(tampered, text)
        path.write_bytes(tampered.encode('utf-8'))
        ok, lines = run_doctor(lib, 'harbor', ten_minute=True)
        self.assertFalse(ok)
        self.assertIn('hash', _blob(lines))

    def test_without_ten_minute_does_not_fail_the_gate(self):
        lib = _open(self)
        (lib.project_dir('harbor') / 'README.md').unlink()
        ok, lines = run_doctor(lib, 'harbor', ten_minute=False)
        self.assertTrue(ok)
        self.assertIn('readme.md is missing', _blob(lines))

    def test_unknown_project(self):
        lib = _open(self)
        ok, lines = run_doctor(lib, 'missing', ten_minute=True)
        self.assertFalse(ok)
        self.assertIn('no project', _blob(lines))
