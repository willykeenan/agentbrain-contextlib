"""Library guarantees: append-only, ledger, inbox, export, git optional."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _unload():
    for key in list(sys.modules):
        if key == 'agentbrain_contextlib' or key.startswith('agentbrain_contextlib.'):
            del sys.modules[key]


def _bind():
    global Library, parse_record
    from agentbrain_contextlib.library import Library
    from agentbrain_contextlib.records import parse_record

WHEN = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _clock():
    return WHEN


def _open(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name) / 'lib'
    lib = Library.init(root, clock=_clock, writer='cli')
    lib.create_project('harbor', 'Harbor', purpose='A fictional headland board.', owners=('mara',))
    return lib


def _ledger(lib):
    path = lib.project_dir('harbor') / '.contextlib' / 'ledger' / 'cli.jsonl'
    rows = []
    for line in path.read_bytes().decode('utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return path, rows


def _chain_hash(obj):
    core = ('action', 'at', 'id', 'path', 'prev_hash', 'seq', 'sha256', 'writer')
    optional = ('author', 'note', 'outcome', 'reason', 'request_key')
    payload = {key: obj[key] for key in core}
    for key in optional:
        if obj.get(key) is not None:
            payload[key] = obj[key]
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_init_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'lib'
            first = Library.init(root, clock=_clock)
            ident = json.loads((root / 'library.json').read_text(encoding='utf-8'))['library_id']
            second = Library.init(root, clock=_clock)
            again = json.loads((root / 'library.json').read_text(encoding='utf-8'))['library_id']
            self.assertEqual(ident, again)
            self.assertTrue((root / 'README.md').is_file())
            self.assertTrue((root / 'INDEX.md').is_file())
            self.assertEqual(first.projects(), second.projects())

    def test_inbox_versus_current_and_review_defaults(self):
        lib = _open(self)
        fact = lib.record(
            'harbor', 'fact', 'Lamp character is Fl W 15s',
            '**Fact:** white flash every 15 seconds.\n',
            author='guest', evidence=('note:signed log',),
        )
        self.assertEqual(fact['status'], 'current')
        self.assertTrue(fact['path'].startswith('facts/'))
        got = lib.get('harbor', fact['id'])
        self.assertEqual(
            date.fromisoformat(got['meta']['review_by']) - WHEN.date(),
            timedelta(days=30),
        )
        guest = lib.record(
            'harbor', 'decision', 'Poll the buoy',
            '**Decision:** do not.\n',
            author='guest', evidence=('note:trial',),
        )
        self.assertEqual(guest['status'], 'proposed')
        self.assertTrue(guest['path'].startswith('inbox/'))
        owner = lib.record(
            'harbor', 'decision', 'Use keeper logs',
            '**Decision:** logs, not AIS.\n',
            author='mara', evidence=('note:keeper log',),
            scope={'lane': 'harbor-board', 'team': 'keepers'},
            tags=('lamp',),
        )
        self.assertEqual(owner['status'], 'current')
        self.assertTrue(owner['path'].startswith('decisions/'))
        self.assertEqual(
            date.fromisoformat(lib.get('harbor', owner['id'])['meta']['review_by']) - WHEN.date(),
            timedelta(days=180),
        )
        approved = lib.record(
            'harbor', 'lesson', 'Offline forms win',
            '**Lesson:** write local first.\n',
            author='guest', evidence=('note:fog book',),
            approved_by='mara — "files first"',
        )
        self.assertEqual(approved['status'], 'current')
        librarian = lib.record(
            'harbor', 'glossary', 'watch',
            '**Meaning:** a four-hour keeper shift.\n',
            author='librarian', evidence=('note:roster',),
        )
        self.assertEqual(librarian['status'], 'current')
        forced = lib.record(
            'harbor', 'fact', 'Held for review',
            '**Fact:** not published yet.\n',
            author='guest', evidence=('note:draft',), status='proposed',
        )
        self.assertEqual(forced['status'], 'proposed')
        requirement = lib.record(
            'harbor', 'requirement', 'Show the character',
            '**Requirement:** the board shows Fl W 15s.\n',
            author='mara', evidence=('note:wall glance',),
        )
        self.assertIsNone(lib.get('harbor', requirement['id'])['meta']['review_by'])
        project = json.loads((lib.project_dir('harbor') / 'project.json').read_text(encoding='utf-8'))
        project['review_defaults']['fact'] = 10
        (lib.project_dir('harbor') / 'project.json').write_text(
            json.dumps(project, indent=2) + '\n', encoding='utf-8',
        )
        short = lib.record(
            'harbor', 'fact', 'Tide is local',
            '**Fact:** mean range is 3.2 metres.\n',
            author='guest', evidence=('note:tide table',),
        )
        self.assertEqual(
            date.fromisoformat(lib.get('harbor', short['id'])['meta']['review_by']) - WHEN.date(),
            timedelta(days=10),
        )

    def test_accept_reject_and_review_keep_the_body(self):
        lib = _open(self)
        proposed = lib.record(
            'harbor', 'decision', 'Try AIS first',
            '**Decision:** later superseded in spirit.\n',
            author='guest', evidence=('note:prototype',),
        )
        body = lib.get('harbor', proposed['id'])['body']
        digest = lib.get('harbor', proposed['id'])['meta']['body_sha256']
        accepted = lib.accept('harbor', proposed['id'], author='mara')
        self.assertEqual(accepted['status'], 'current')
        self.assertTrue(accepted['path'].startswith('decisions/'))
        self.assertFalse((lib.project_dir('harbor') / proposed['path']).exists())
        got = lib.get('harbor', proposed['id'])
        self.assertEqual(got['body'], body)
        self.assertEqual(got['meta']['body_sha256'], digest)
        other = lib.record(
            'harbor', 'lesson', 'Skip this',
            '**Lesson:** not ready.\n',
            author='guest', evidence=('note:no',),
        )
        rejected = lib.reject('harbor', other['id'], 'folded into the brief', author='mara')
        self.assertEqual(rejected['status'], 'retired')
        self.assertTrue(rejected['path'].startswith('inbox/rejected/'))
        self.assertEqual(lib.list('harbor', status='proposed'), [])
        confirmed = lib.review(
            'harbor', proposed['id'], 'confirm', 'still right',
            author='mara', next_review_by='2027-01-15',
        )
        self.assertEqual(confirmed['outcome'], 'confirm')
        self.assertEqual(lib.get('harbor', proposed['id'])['meta']['review_by'], '2027-01-15')
        self.assertEqual(lib.get('harbor', proposed['id'])['body'], body)

    def test_supersede_moves_file_and_keeps_body_hash(self):
        lib = _open(self)
        old = lib.record(
            'harbor', 'decision', 'Poll AIS every five seconds',
            '**Decision:** treat the nearest report as the lamp.\n',
            author='mara', evidence=('note:early prototype',),
        )
        before = lib.get('harbor', old['id'])
        old_path = lib.project_dir('harbor') / before['path']
        old_file_sha = hashlib.sha256(old_path.read_bytes()).hexdigest()
        new = lib.record(
            'harbor', 'decision', 'Use keeper logs',
            '**Decision:** the lamp is what the keeper signed.\n',
            author='mara', evidence=('note:keeper log',),
            supersedes=(old['id'],),
        )
        moved = lib.supersede(
            'harbor', old['id'], new['id'], 'AIS is traffic, not lamp status', author='mara',
        )
        self.assertEqual(moved['status'], 'superseded')
        self.assertIn('superseded', Path(moved['path']).parts)
        self.assertFalse(old_path.exists())
        after = lib.get('harbor', old['id'])
        self.assertEqual(after['body'], before['body'])
        self.assertEqual(after['meta']['body_sha256'], before['meta']['body_sha256'])
        self.assertEqual(
            hashlib.sha256(after['body'].encode('utf-8')).hexdigest(),
            before['meta']['body_sha256'],
        )
        self.assertEqual(after['meta']['status'], 'superseded')
        self.assertEqual(after['meta']['superseded_by'], new['id'])
        self.assertEqual(after['supersession_chain'], [old['id'], new['id']])
        self.assertEqual(lib.get('harbor', new['id'])['supersession_chain'], [old['id'], new['id']])
        _path, rows = _ledger(lib)
        creates = [row for row in rows if row['action'] == 'record' and row['id'] == old['id']]
        supers = [row for row in rows if row['action'] == 'supersede' and row['id'] == old['id']]
        self.assertEqual(creates[0]['sha256'], old_file_sha)
        new_bytes = (lib.project_dir('harbor') / after['path']).read_bytes()
        self.assertEqual(supers[0]['sha256'], hashlib.sha256(new_bytes).hexdigest())
        self.assertNotEqual(supers[0]['sha256'], old_file_sha)

    def test_ledger_hash_chain(self):
        lib = _open(self)
        lib.record(
            'harbor', 'fact', 'First', '**Fact:** one.\n',
            author='mara', evidence=('note:one',),
        )
        lib.record(
            'harbor', 'fact', 'Second', '**Fact:** two.\n',
            author='mara', evidence=('note:two',),
        )
        _path, rows = _ledger(lib)
        self.assertGreaterEqual(len(rows), 2)
        prev = None
        for index, row in enumerate(rows, 1):
            self.assertEqual(row['seq'], index)
            self.assertEqual(row['prev_hash'], prev)
            self.assertEqual(row['hash'], _chain_hash(row))
            self.assertEqual(row['writer'], 'cli')
            prev = row['hash']

    def test_refuses_secret_and_home_path(self):
        lib = _open(self)
        directory = lib.project_dir('harbor')
        before = {path.relative_to(directory).as_posix() for path in directory.rglob('*.md')}
        token = 'sk' + '-' + 'Abcd1234'
        with self.assertRaises(ValueError) as caught:
            lib.record(
                'harbor', 'fact', 'Bad token', '**Fact:** ' + token + '\n',
                author='mara', evidence=('note:no',),
            )
        self.assertIn('secret', str(caught.exception).lower())
        self.assertNotIn(token, str(caught.exception))
        home = '/' + 'Users/' + 'ada/notes.txt'
        with self.assertRaises(ValueError) as caught:
            lib.record(
                'harbor', 'fact', 'Bad path', 'see ' + home + '\n',
                author='mara', evidence=('note:no',),
            )
        self.assertIn('home', str(caught.exception).lower())
        self.assertNotIn(home, str(caught.exception))
        after = {path.relative_to(directory).as_posix() for path in directory.rglob('*.md')}
        self.assertEqual(before, after)

    def test_request_key_is_idempotent(self):
        lib = _open(self)
        first = lib.record(
            'harbor', 'fact', 'Original title', '**Fact:** original.\n',
            author='mara', evidence=('note:once',), request_key='batch-1',
        )
        second = lib.record(
            'harbor', 'fact', 'Original title', '**Fact:** original.\n',
            author='mara', evidence=('note:once',), request_key='batch-1',
        )
        self.assertEqual(second, first)
        with self.assertRaises(ValueError) as caught:
            lib.record(
                'harbor', 'fact', 'Different title', '**Fact:** other.\n',
                author='mara', evidence=('note:twice',), request_key='batch-1',
            )
        self.assertIn('request_key', str(caught.exception))
        self.assertEqual(lib.get('harbor', first['id'])['meta']['title'], 'Original title')
        _path, rows = _ledger(lib)
        keyed = [row for row in rows if row.get('request_key') == 'batch-1']
        self.assertEqual(len(keyed), 1)
        other = lib.record(
            'harbor', 'fact', 'Third', '**Fact:** three.\n',
            author='mara', evidence=('note:three',), request_key='batch-2',
        )
        self.assertNotEqual(other['id'], first['id'])

    def test_evidence_states(self):
        lib = _open(self)
        directory = lib.project_dir('harbor')
        pinned = directory / 'exports' / 'pin.txt'
        pinned.parent.mkdir(parents=True, exist_ok=True)
        payload = b'hello\n'
        pinned.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        rec = lib.record(
            'harbor', 'source', 'Pinned note',
            '**Source:** a local file.\n',
            author='mara',
            evidence=(
                {'ref': 'project:exports/pin.txt', 'sha256': digest},
                {'ref': 'project:exports/missing.txt', 'sha256': digest},
                {'ref': 'url:https://example.com/x'},
            ),
        )
        states = {item['ref']: item['state'] for item in lib.get('harbor', rec['id'])['evidence']}
        self.assertEqual(states['project:exports/pin.txt'], 'ok')
        self.assertEqual(states['project:exports/missing.txt'], 'missing')
        self.assertEqual(states['url:https://example.com/x'], 'unchecked')
        pinned.write_bytes(b'changed\n')
        states = {item['ref']: item['state'] for item in lib.get('harbor', rec['id'])['evidence']}
        self.assertEqual(states['project:exports/pin.txt'], 'changed')

    def test_export_import_keeps_hashes(self):
        lib = _open(self)
        kept = []
        for title, private in (('Public lamp', False), ('Public tide', False), ('Private watch', True)):
            rec = lib.record(
                'harbor', 'fact', title, '**Fact:** %s.\n' % title,
                author='mara', evidence=('note:%s' % title,),
                sensitivity='private' if private else 'normal',
            )
            got = lib.get('harbor', rec['id'])
            kept.append((rec['id'], got['meta']['body_sha256'], got['body'], private))
        out = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(out, ignore_errors=True))
        exported = lib.export('harbor', out / 'pub', include_private=False)
        self.assertEqual(exported['records'], 2)
        self.assertEqual(
            exported['sha256'],
            hashlib.sha256(Path(exported['path']).read_bytes()).hexdigest(),
        )
        with zipfile.ZipFile(exported['path']) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.startswith('facts/') for name in names))
        self.assertNotIn('project.json', [name for name in names if 'Private' in name])
        fresh_root = out / 'lib2'
        fresh = Library.init(fresh_root, clock=_clock)
        result = fresh.import_bundle(exported['path'])
        self.assertEqual(result['project'], 'harbor')
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(result['records'], 2)
        for ident, digest, body, private in kept:
            if private:
                with self.assertRaises(ValueError):
                    fresh.get('harbor', ident)
                continue
            got = fresh.get('harbor', ident)
            self.assertEqual(got['meta']['body_sha256'], digest)
            self.assertEqual(got['body'], body)
        full = lib.export('harbor', out / 'all', include_private=True)
        self.assertEqual(full['records'], 3)
        other = Library.init(out / 'lib3', clock=_clock)
        imported = other.import_bundle(full['path'])
        self.assertEqual(imported['conflicts'], [])
        self.assertEqual(imported['records'], 3)
        for ident, digest, body, _private in kept:
            got = other.get('harbor', ident)
            self.assertEqual(got['meta']['body_sha256'], digest)
            self.assertEqual(got['body'], body)
        victim = kept[0][0]
        path = other.project_dir('harbor') / other.get('harbor', victim)['path']
        text = path.read_bytes().decode('utf-8')
        old_hash = kept[0][1]
        tampered = text.replace(old_hash, '0' * 64, 1)
        path.write_bytes(tampered.encode('utf-8'))
        again = other.import_bundle(full['path'])
        self.assertIn(victim, again['conflicts'])
        reread = parse_record(path.read_bytes().decode('utf-8'))
        self.assertEqual(reread['meta']['body_sha256'], '0' * 64)

    def test_review_due(self):
        lib = _open(self)
        due = lib.record(
            'harbor', 'fact', 'Due fact', '**Fact:** due.\n',
            author='mara', evidence=('note:due',), review_by='2026-09-26',
        )
        later = lib.record(
            'harbor', 'fact', 'Later fact', '**Fact:** later.\n',
            author='mara', evidence=('note:later',), review_by='2026-12-01',
        )
        found = lib.review_due('harbor')
        ids = [item['id'] for item in found]
        self.assertIn(due['id'], ids)
        self.assertNotIn(later['id'], ids)

    def test_git_is_optional(self):
        import subprocess
        calls = []
        real_run = subprocess.run

        def _run(cmd, *args, **kwargs):
            flat = cmd if isinstance(cmd, str) else ' '.join(str(part) for part in cmd)
            if 'git' in flat.split():
                calls.append(flat)
                raise AssertionError('git invoked')
            return real_run(cmd, *args, **kwargs)

        old_path = os.environ.get('PATH', '')
        os.environ['PATH'] = ''
        subprocess.run = _run
        try:
            lib = _open(self)
            rec = lib.record(
                'harbor', 'fact', 'No git needed', '**Fact:** files only.\n',
                author='mara', evidence=('note:disk',),
            )
            other = lib.record(
                'harbor', 'decision', 'Still no git', '**Decision:** stay on disk.\n',
                author='mara', evidence=('note:disk',),
            )
            lib.supersede('harbor', other['id'], rec['id'], 'not really', author='mara')
            lib.regenerate('harbor')
            out = Path(tempfile.mkdtemp())
            self.addCleanup(lambda: __import__('shutil').rmtree(out, ignore_errors=True))
            exported = lib.export('harbor', out)
            dest = Library.init(out / 'copy', clock=_clock)
            dest.import_bundle(exported['path'])
            from agentbrain_contextlib.index import Index
            self.assertGreater(Index(lib).rebuild('harbor'), 0)
        finally:
            subprocess.run = real_run
            os.environ['PATH'] = old_path
        self.assertEqual(calls, [])




class TestConcurrentWriters(unittest.TestCase):
    """Several writers (CLI, MCP server, agents) share one library."""

    def setUp(self):
        _unload()
        _bind()

    def test_ledger_chain_survives_threads_and_processes(self):
        import subprocess
        import threading
        lib = _open(self)
        src = str(Path(__file__).resolve().parents[1] / 'src')
        code = (
            'import sys; sys.path.insert(0, sys.argv[1]);'
            'from agentbrain_contextlib.library import Library;'
            'L = Library(sys.argv[2]);'
            '[L.record("harbor", "fact", "P%s-%d" % (sys.argv[3], i), "**Fact:** p.\\n",'
            ' author="mara", evidence=("note:proc",)) for i in range(10)]'
        )
        procs = [subprocess.Popen([sys.executable, '-c', code, src, str(lib.root), str(k)]) for k in range(3)]
        errors = []

        def write(i):
            try:
                lib.record('harbor', 'fact', 'T%d' % i, '**Fact:** t.\n', author='mara', evidence=('note:thread',))
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(repr(exc))

        threads = [threading.Thread(target=write, args=(i,)) for i in range(15)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([p.wait() for p in procs], [0, 0, 0])
        self.assertEqual(errors, [])
        _path, rows = _ledger(lib)
        seqs = [row['seq'] for row in rows]
        self.assertEqual(len(seqs), len(set(seqs)), 'duplicate ledger sequence numbers')
        for before, after in zip(rows, rows[1:]):
            self.assertEqual(after['prev_hash'], before['hash'], 'ledger hash chain broken')

    def test_request_key_is_single_use_under_concurrency(self):
        import threading
        lib = _open(self)
        results = []

        def write():
            results.append(lib.record('harbor', 'fact', 'Once', '**Fact:** once.\n', author='mara',
                                      evidence=('note:once',), request_key='same-key')['id'])

        threads = [threading.Thread(target=write) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(results)), 1)


if __name__ == '__main__':
    unittest.main()
