"""Static Hugging Face Space: build.py, library.json, index.html."""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / 'space'
SAMPLE = ROOT / 'examples' / 'sample-library'
PROJECT = SAMPLE / 'projects' / 'lighthouse-app'
BUILD = SPACE / 'build.py'
LIBRARY_JSON = SPACE / 'library.json'
INDEX = SPACE / 'index.html'
README = SPACE / 'README.md'

SKIP_NAMES = {
    'README.md',
    'INDEX.md',
    'BRIEF.md',
    'GLOSSARY.md',
    'TIMELINE.md',
}
HTTP_RE = re.compile(r'https?://', re.IGNORECASE)
ID_RE = re.compile(r'^(dec|req|fact|les|glo|src|ret|note)-\d{8}-[0-9a-f]{4}$')


def sample_record_ids():
    ids = []
    for path in sorted(PROJECT.rglob('*.md')):
        if path.name in SKIP_NAMES:
            continue
        text = path.read_text(encoding='utf-8')
        if not text.startswith('---'):
            continue
        for line in text.splitlines()[1:]:
            if line.startswith('id:'):
                ids.append(line.split(':', 1)[1].strip())
                break
    return ids


def load_space_json():
    return json.loads(LIBRARY_JSON.read_text(encoding='utf-8'))


def all_records(payload):
    records = []
    for project in payload.get('projects') or []:
        records.extend(project.get('records') or [])
    return records


class TestSpaceFiles(unittest.TestCase):
    def test_required_files_exist(self):
        for path in (BUILD, LIBRARY_JSON, INDEX, README):
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 0, path)

    def test_readme_front_matter(self):
        text = README.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---'), 'README needs YAML front matter')
        end = text.find('\n---', 3)
        self.assertGreater(end, 0)
        fm = text[4:end]
        self.assertRegex(fm, r'(?m)^title:\s*ContextLib\s*$')
        self.assertRegex(fm, r'(?m)^sdk:\s*static\s*$')


class TestBuildPy(unittest.TestCase):
    def test_stdlib_only_and_uses_library_api(self):
        src = BUILD.read_text(encoding='utf-8')
        tree = ast.parse(src)
        allowed_top = {'json', 'sys', 'pathlib', 'os', '__future__'}
        allowed_from = {'agentbrain_contextlib', 'agentbrain_contextlib.library'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split('.')[0]
                    self.assertIn(root, allowed_top)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ''
                root = mod.split('.')[0]
                if root == 'agentbrain_contextlib':
                    self.assertIn(mod, allowed_from)
                    names = {alias.name for alias in node.names}
                    self.assertTrue('Library' in names or names == {'*'})
                else:
                    self.assertIn(root, allowed_top)
        self.assertIn('Library', src)
        self.assertIn('projects(', src)
        self.assertIn('.get(', src)
        self.assertIn('.list(', src)

    def test_regenerates_library_json_identically(self):
        original = LIBRARY_JSON.read_bytes()
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT / 'src') + (
            os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else ''
        )
        result = subprocess.run(
            [sys.executable, str(BUILD)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        regenerated = LIBRARY_JSON.read_bytes()
        self.assertEqual(regenerated, original)

    def test_write_to_temp_matches_committed_file(self):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT / 'src')
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'library.json'
            result = subprocess.run(
                [sys.executable, str(BUILD), str(SAMPLE), str(dest)],
                cwd=str(tmp),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                dest.read_bytes(),
                LIBRARY_JSON.read_bytes(),
            )


class TestLibraryJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = load_space_json()
        cls.records = all_records(cls.payload)
        cls.ids = [rec['meta']['id'] for rec in cls.records]
        cls.sample_ids = sample_record_ids()

    def test_format_and_library_meta(self):
        self.assertEqual(self.payload['format'], 'contextlib/1')
        library = self.payload['library']
        sample_lib = json.loads((SAMPLE / 'library.json').read_text(encoding='utf-8'))
        self.assertEqual(library, sample_lib)
        self.assertEqual(library['format'], 'contextlib/1')
        self.assertIn('library_id', library)
        self.assertIn('created', library)

    def test_project_meta_and_brief(self):
        self.assertEqual(len(self.payload['projects']), 1)
        project = self.payload['projects'][0]
        meta = project['meta']
        expected = json.loads((PROJECT / 'project.json').read_text(encoding='utf-8'))
        self.assertEqual(meta, expected)
        self.assertEqual(meta['slug'], 'lighthouse-app')
        brief = project['brief']
        on_disk = (PROJECT / 'BRIEF.md').read_text(encoding='utf-8')
        self.assertEqual(brief, on_disk)
        self.assertIn('Lighthouse App', brief)
        self.assertLessEqual(len(brief.encode('utf-8')), 8192)

    def test_every_sample_record_is_present(self):
        self.assertTrue(self.sample_ids)
        self.assertEqual(sorted(self.ids), sorted(self.sample_ids))
        self.assertGreaterEqual(len(self.ids), 10)
        self.assertEqual(len(self.ids), len(set(self.ids)))

    def test_each_record_has_meta_and_body(self):
        for rec in self.records:
            meta = rec['meta']
            self.assertIsInstance(meta, dict)
            self.assertRegex(meta['id'], ID_RE)
            self.assertIn('type', meta)
            self.assertIn('title', meta)
            self.assertIn('status', meta)
            self.assertTrue(str(rec['body']).strip(), meta['id'])
            self.assertIn('path', rec)
            self.assertIn('supersession_chain', rec)
            self.assertIsInstance(rec['supersession_chain'], list)

    def test_supersession_chain_for_sample_decision(self):
        by_id = {rec['meta']['id']: rec for rec in self.records}
        current = by_id['dec-20260912-a1b2']
        old = by_id['dec-20260905-c0de']
        self.assertEqual(current['meta']['status'], 'current')
        self.assertEqual(old['meta']['status'], 'superseded')
        self.assertIn('dec-20260905-c0de', current['meta'].get('supersedes') or [])
        self.assertEqual(old['meta'].get('superseded_by'), 'dec-20260912-a1b2')
        chain = current['supersession_chain']
        self.assertIn('dec-20260905-c0de', chain)
        self.assertIn('dec-20260912-a1b2', chain)


class TestIndexHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding='utf-8')

    def test_single_self_contained_file(self):
        self.assertIn('<!DOCTYPE html>', self.html)
        self.assertEqual(self.html.count('<html'), 1)
        self.assertNotIn('<script src=', self.html.lower())
        self.assertNotIn('<link ', self.html.lower())
        self.assertNotIn('@import', self.html.lower())
        self.assertNotIn('cdn', self.html.lower())

    def test_loads_library_json(self):
        self.assertIn('library.json', self.html)
        self.assertRegex(
            self.html,
            r"""fetch\(\s*['\"]library\.json['\"]\s*\)""",
        )

    def test_no_http_or_https_resource(self):
        # Plain navigation links are fine; nothing may be *loaded* from the network.
        loaded = re.sub(r'<a\s[^>]*href="https://[^"]+"[^>]*>', '<a>', self.html)
        self.assertIsNone(HTTP_RE.search(loaded), 'index.html must not load network resources')
        lowered = self.html.lower()
        for needle in (
            'googleapis',
            'gstatic',
            'cloudflare',
            'jsdelivr',
            'unpkg',
            'cdnjs',
            'fonts.google',
        ):
            self.assertNotIn(needle, lowered)

    def test_read_only_ui_contract(self):
        self.assertIn('viewport', self.html)
        self.assertIn('width=device-width', self.html)
        self.assertRegex(self.html, r'type="search"|type=\'search\'')
        self.assertIn('badge', self.html)
        self.assertIn('current', self.html)
        self.assertIn('superseded', self.html)
        self.assertIn('Supersedes', self.html)
        self.assertIn('Superseded by', self.html)
        self.assertIn('Project brief', self.html)
        self.assertIn('id="q"', self.html)
        self.assertIn('font-size: 16px', self.html)

    def test_groups_by_type(self):
        for label in (
            'Decisions',
            'Requirements',
            'Facts',
            'Lessons',
            'Glossary',
            'Sources',
            'Returns',
            'Brief notes',
        ):
            self.assertIn(label, self.html)


if __name__ == '__main__':
    unittest.main()
