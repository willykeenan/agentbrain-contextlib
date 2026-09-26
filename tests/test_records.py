"""Format round trip, validation, and the sample library."""
from __future__ import annotations

import hashlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


def _unload():
    for key in list(sys.modules):
        if key == 'agentbrain_contextlib' or key.startswith('agentbrain_contextlib.'):
            del sys.modules[key]


def _bind():
    global PREFIX, TYPES, new_id, parse_record, render_record, split_record, validate
    from agentbrain_contextlib.records import (
        PREFIX,
        TYPES,
        new_id,
        parse_record,
        render_record,
        split_record,
        validate,
    )

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'examples' / 'sample-library' / 'projects' / 'lighthouse-app'


def _meta():
    return {
        'id': 'dec-20260926-7f3a',
        'type': 'decision',
        'title': 'Use plain files as the source of truth',
        'status': 'current',
        'project': 'lighthouse-app',
        'scope': {'lane': 'workstream', 'team': 'owner'},
        'created': '2026-09-26T14:03:00Z',
        'author': 'mara',
        'approved_by': 'mara — "files first, database is only an index"',
        'evidence': [
            {'ref': 'project:BRIEF.md'},
            {'ref': 'url:https://example.com/x'},
        ],
        'supersedes': [],
        'superseded_by': None,
        'review_by': '2027-03-25',
        'tags': ['storage', 'library'],
        'sensitivity': 'normal',
    }


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_render_parse_round_trip(self):
        body = '**Decision:** Keep the Markdown files as the source of truth.\n'
        meta = _meta()
        text = render_record(meta, body)
        parsed = parse_record(text)
        self.assertEqual(parsed['body'], body)
        self.assertEqual(parsed['meta']['title'], meta['title'])
        self.assertEqual(parsed['meta']['scope'], meta['scope'])
        self.assertEqual(parsed['meta']['approved_by'], meta['approved_by'])
        self.assertEqual(parsed['meta']['evidence'], meta['evidence'])
        self.assertIsNone(parsed['meta']['superseded_by'])
        self.assertEqual(parsed['meta']['tags'], meta['tags'])
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        self.assertEqual(parsed['meta']['body_sha256'], digest)
        again = render_record(parsed['meta'], parsed['body'])
        self.assertEqual(again, text)
        self.assertEqual(validate(parsed['meta'], parsed['body']), [])

    def test_new_id_shape(self):
        when = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)
        for type_, prefix in PREFIX.items():
            ident = new_id(type_, when=when)
            self.assertRegex(ident, r'^%s-20260926-[0-9a-f]{4}$' % prefix)
        with self.assertRaises(ValueError):
            new_id('not-a-type')

    def test_validate_reports_problems(self):
        body = '**Decision:** files.\n'
        text = render_record(_meta(), body)
        parsed = parse_record(text)
        parsed['meta']['body_sha256'] = '0' * 64
        problems = validate(parsed['meta'], parsed['body'])
        self.assertTrue(any('body_sha256' in item for item in problems))
        parsed = parse_record(text)
        parsed['meta']['evidence'] = [{'ref': 'url:http://example.com/x'}]
        problems = validate(parsed['meta'], parsed['body'])
        self.assertTrue(any('evidence' in item for item in problems))
        parsed = parse_record(text)
        parsed['meta']['evidence'] = [{'ref': 'project:../secret.md'}]
        problems = validate(parsed['meta'], parsed['body'])
        self.assertTrue(any('evidence' in item for item in problems))

    def test_parse_rejects_bad_files(self):
        with self.assertRaises(ValueError):
            parse_record('hello')
        with self.assertRaises(ValueError):
            parse_record('---\nid: dec-20260926-7f3a\n')


class TestSampleLibrary(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_every_sample_record_parses_and_validates(self):
        files = []
        for path in sorted(SAMPLE.rglob('*.md')):
            if path.name in {'README.md', 'INDEX.md', 'BRIEF.md', 'GLOSSARY.md', 'TIMELINE.md'}:
                continue
            text = path.read_bytes().decode('utf-8')
            if not text.startswith('---'):
                continue
            files.append((path, text))
        self.assertEqual(len(files), 12)
        seen = set()
        for path, text in files:
            front, body = split_record(text)
            self.assertEqual('---\n' + front + '\n---\n' + body, text, path.name)
            parsed = parse_record(text)
            meta = parsed['meta']
            seen.add(meta['type'])
            digest = hashlib.sha256(parsed['body'].encode('utf-8')).hexdigest()
            self.assertEqual(meta['body_sha256'], digest, path.name)
            self.assertEqual(validate(meta, parsed['body']), [], path.name)
            self.assertEqual(meta['project'], 'lighthouse-app')
        self.assertEqual(seen, set(TYPES))

    def test_sample_decision_fields(self):
        path = SAMPLE / 'decisions' / '2026-09-12_use-keeper-logs-as-the-lamp-status-source-of-truth_a1b2.md'
        parsed = parse_record(path.read_bytes().decode('utf-8'))
        meta = parsed['meta']
        self.assertEqual(meta['id'], 'dec-20260912-a1b2')
        self.assertEqual(meta['status'], 'current')
        self.assertEqual(meta['scope'], {'lane': 'harbor-board', 'team': 'keepers'})
        self.assertEqual(meta['supersedes'], ['dec-20260905-c0de'])
        self.assertEqual(meta['tags'], ['lamp', 'keeper-log', 'ais'])
        self.assertIn('files first', meta['approved_by'])
        self.assertTrue(parsed['body'].startswith('**Decision:**'))

    def test_matches_packaging_parser(self):
        from test_packaging import parse_record as other_parse

        for path in sorted(SAMPLE.rglob('*.md')):
            text = path.read_bytes().decode('utf-8')
            if not text.startswith('---'):
                continue
            if path.name in {'README.md', 'INDEX.md', 'BRIEF.md', 'GLOSSARY.md', 'TIMELINE.md'}:
                continue
            self.assertEqual(parse_record(text), other_parse(text), path.name)


if __name__ == '__main__':
    unittest.main()
