"""On-disk project library. Markdown is the source of truth.

Apache-2.0, copyright KE Studios. Git is not required.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agentbrain_contextlib.records import (
    ID_RE,
    REVIEW_DAYS,
    STATUSES,
    TYPE_DIR,
    TYPES,
    body_sha256,
    format_time,
    iter_record_texts,
    new_id,
    parse_record,
    render_record,
    slugify,
    split_record,
    validate,
)
from agentbrain_contextlib.scanner import scan_text

try:  # POSIX; on Windows only threads in one process are serialized.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

_LOCKS_GUARD = threading.Lock()
_LOCKS = {}
_HELD = threading.local()


@contextlib.contextmanager
def _exclusive(path: Path):
    """Re-entrant exclusive lock across threads and processes for one lock file."""
    key = str(path)
    held = getattr(_HELD, 'depth', None)
    if held is None:
        held = _HELD.depth = {}
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    with _LOCKS_GUARD:
        local = _LOCKS.setdefault(key, threading.Lock())
    with local:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a+') as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held[key] = 1
            try:
                yield
            finally:
                held[key] = 0
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _writes(method):
    """Serialize a mutating Library method per project, so request keys and the
    ledger hash chain stay correct with several writers (CLI, MCP, agents)."""
    @functools.wraps(method)
    def wrapper(self, project, *args, **kwargs):
        with self._write_lock(project):
            return method(self, project, *args, **kwargs)
    return wrapper

__all__ = ['Library', 'ledger_hash', 'writer_slug']

_SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_LEDGER_CORE = ('action', 'at', 'id', 'path', 'prev_hash', 'seq', 'sha256', 'writer')
_LEDGER_OPTIONAL = ('author', 'note', 'outcome', 'reason', 'request_key')


def writer_slug(writer: str) -> str:
    text = re.sub(r'[^A-Za-z0-9]+', '-', (writer or '').strip()).strip('-').lower()
    if not text:
        raise ValueError('writer is invalid')
    return text[:80]


def ledger_hash(entry: dict) -> str:
    """SHA-256 of the canonical ledger payload. The ``hash`` field is excluded."""
    payload = {key: entry[key] for key in _LEDGER_CORE}
    for key in _LEDGER_OPTIONAL:
        if entry.get(key) is not None:
            payload[key] = entry[key]
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def _write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(path), flags, 0o644)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
    except Exception:
        if path.exists():
            path.unlink()
        raise


def _read_text(path: Path) -> str:
    return path.read_bytes().decode('utf-8')


def _dump_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + '\n')


def _load_json(path: Path):
    return json.loads(_read_text(path))


def _single_line(value, label: str) -> None:
    if isinstance(value, str) and ('\n' in value or '\r' in value or '\x00' in value):
        raise ValueError('%s must be a single line' % label)


def _refuse_if_flagged(text: str) -> None:
    hits = scan_text(text or '')
    if not hits:
        return
    kinds = []
    for hit in hits:
        kind = hit.get('kind')
        if kind not in kinds:
            kinds.append(kind)
    labels = []
    for kind in kinds:
        if kind == 'secret':
            labels.append('a secret')
        elif kind == 'abs-path':
            labels.append('an absolute home path')
    if not labels:
        labels.append('disallowed text')
    raise ValueError('refusing to write ' + ' and '.join(labels))


def _patch_front(text: str, updates: dict) -> str:
    """Replace named front-matter lines. The body is not rewritten."""
    front, body = split_record(text)
    lines = front.split('\n')
    seen = set()
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line[:1] in (' ', '\t'):
            continue
        name, sep, _rest = line.partition(':')
        if not sep:
            continue
        key = name.strip()
        if key in updates:
            lines[index] = '%s: %s' % (key, updates[key])
            seen.add(key)
    missing = [key for key in updates if key not in seen]
    if missing:
        insert_at = len(lines)
        for index, line in enumerate(lines):
            if line.startswith('body_sha256:'):
                insert_at = index
                break
        extra = ['%s: %s' % (key, updates[key]) for key in missing]
        lines = lines[:insert_at] + extra + lines[insert_at:]
    rebuilt = '---\n' + '\n'.join(lines) + '\n---\n' + body
    _front, new_body = split_record(rebuilt)
    if new_body != body:
        raise ValueError('refusing to rewrite the record body')
    return rebuilt


def _is_librarian(author: str) -> bool:
    name = (author or '').strip().lower()
    return name == 'librarian' or name.startswith('librarian:') or name == 'service:librarian'


def _rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


class Library:
    def __init__(self, root, clock=None, writer='cli'):
        if writer is None or not str(writer).strip():
            raise ValueError('writer is required')
        _single_line(str(writer), 'writer')
        writer_slug(str(writer))
        self.root = Path(root)
        self.clock = clock
        self.writer = str(writer)
        self._id_cache = {}

    @classmethod
    def init(cls, root, clock=None, writer='cli') -> 'Library':
        """Create README, INDEX, and library.json when they are missing."""
        library = cls(root, clock=clock, writer=writer)
        library.root.mkdir(parents=True, exist_ok=True)
        (library.root / 'projects').mkdir(exist_ok=True)
        meta_path = library.root / 'library.json'
        if not meta_path.exists():
            _dump_json(meta_path, {
                'format': 'contextlib/1',
                'library_id': _new_library_id(),
                'created': format_time(library._now()),
            })
        readme = library.root / 'README.md'
        if not readme.exists():
            _write_text(readme, _library_readme())
        index = library.root / 'INDEX.md'
        if not index.exists():
            _write_text(index, _empty_root_index())
        ignore = library.root / '.gitignore'
        if not ignore.exists():
            # Records and ledgers are the library; the index and locks are rebuildable.
            _write_text(ignore, '**/.contextlib/index.sqlite*\n**/.contextlib/locks/\n')
        return library

    def projects(self) -> list:
        base = self.root / 'projects'
        if not base.is_dir():
            return []
        found = []
        for child in sorted(base.iterdir(), key=lambda item: item.name):
            if not child.is_dir():
                continue
            path = child / 'project.json'
            if not path.is_file():
                continue
            try:
                data = _load_json(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get('slug'):
                found.append(data)
        found.sort(key=lambda item: item.get('slug') or '')
        return found

    def read_project(self, slug: str) -> dict:
        path = self.project_dir(slug) / 'project.json'
        if not path.is_file():
            raise ValueError('no project %s' % slug)
        try:
            data = _load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('invalid project.json for %s' % slug) from exc
        if not isinstance(data, dict):
            raise ValueError('invalid project.json for %s' % slug)
        return data

    def project_dir(self, slug: str) -> Path:
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            raise ValueError('invalid project slug')
        return self.root / 'projects' / slug

    def create_project(self, slug, name, purpose='', owners=()) -> dict:
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            raise ValueError('invalid project slug')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('project name is required')
        _single_line(name, 'name')
        _single_line(purpose or '', 'purpose')
        if isinstance(owners, str) or owners is None:
            raise ValueError('owners must be a list of identities')
        owner_list = []
        for owner in owners:
            if not isinstance(owner, str) or not owner.strip():
                raise ValueError('owners must be a list of identities')
            _single_line(owner, 'owner')
            owner_list.append(owner)
        _refuse_if_flagged('\n'.join([slug, name, purpose or ''] + owner_list))
        if not (self.root / 'library.json').is_file():
            raise ValueError('library is not initialized')
        directory = self.project_dir(slug)
        if (directory / 'project.json').exists():
            raise ValueError('project %s already exists' % slug)
        self._ensure_project_dirs(directory)
        payload = {
            'slug': slug,
            'name': name.strip(),
            'purpose': purpose or '',
            'created': format_time(self._now()),
            'owners': owner_list,
            'review_defaults': {key: REVIEW_DAYS[key] for key in REVIEW_DAYS},
        }
        _dump_json(directory / 'project.json', payload)
        inbox_readme = directory / 'inbox' / 'README.md'
        if not inbox_readme.exists():
            _write_text(inbox_readme, _inbox_readme())
        self.regenerate(slug)
        return self.read_project(slug)

    @_writes
    def record(self, project, type_, title, body, *, author, evidence=(), supersedes=(),
               review_by=None, scope=None, tags=(), sensitivity='normal', approved_by=None,
               status=None, request_key=None) -> dict:
        """Write one record. Returns ``{'id', 'path', 'status'}``."""
        meta_project = self.read_project(project)
        if type_ not in TYPES:
            raise ValueError('unknown type')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('title is required')
        if not isinstance(body, str):
            raise ValueError('body must be a string')
        if not isinstance(author, str) or not author.strip():
            raise ValueError('author is required')
        _single_line(title, 'title')
        _single_line(author, 'author')
        if approved_by is not None:
            if not isinstance(approved_by, str):
                raise ValueError('approved_by must be a string')
            _single_line(approved_by, 'approved_by')
        if request_key is not None:
            if not isinstance(request_key, str) or not request_key:
                raise ValueError('request_key must be a string')
            _single_line(request_key, 'request_key')
        if sensitivity not in ('normal', 'private'):
            raise ValueError('sensitivity must be normal or private')
        if status is not None and status not in STATUSES:
            raise ValueError('unknown status')
        evidence_items = _normalize_evidence(evidence)
        supersede_ids = _normalize_ids(supersedes, 'supersedes')
        tag_list = _normalize_tags(tags)
        if scope is not None:
            scope = _normalize_scope(scope)
        if review_by is not None and (not isinstance(review_by, str) or not _DATE_RE.match(review_by)):
            raise ValueError('review_by must be YYYY-MM-DD')
        if request_key:
            prior = self._find_request(project, request_key)
            if prior is not None:
                _path, prior_meta, prior_body = self._load(project, prior['id'])
                if (prior_meta.get('type'), prior_meta.get('title'), prior_body) != (type_, title, body):
                    raise ValueError('request_key was already used for a different record')
                return prior
        created_dt = self._now()
        created = format_time(created_dt)
        if review_by is None:
            days = self._review_days(meta_project, type_)
            if days is None:
                review_value = None
            else:
                review_value = (created_dt.date() + timedelta(days=int(days))).isoformat()
        else:
            review_value = review_by
        if status is None:
            status = self._default_status(
                meta_project, type_, author, evidence_items, approved_by,
            )
        ident = self._allocate_id(project, type_, created_dt)
        meta = {
            'id': ident,
            'type': type_,
            'title': title.strip(),
            'status': status,
            'project': project,
            'created': created,
            'author': author,
            'evidence': evidence_items,
            'supersedes': supersede_ids,
            'superseded_by': None,
            'review_by': review_value,
            'tags': tag_list,
            'sensitivity': sensitivity,
        }
        if scope:
            meta['scope'] = scope
        if approved_by:
            meta['approved_by'] = approved_by
        text = render_record(meta, body)
        side = request_key or ''
        _refuse_if_flagged(text + ('\n' + side if side else ''))
        parsed = parse_record(text)
        problems = validate(parsed['meta'], parsed['body'])
        if problems:
            raise ValueError('; '.join(problems))
        if parsed['body'] != body:
            raise ValueError('record body did not round-trip')
        filename = '%s_%s_%s.md' % (created[:10], slugify(title), ident.rsplit('-', 1)[1])
        rel = _dest_rel(type_, status, filename)
        directory = self.project_dir(project)
        path = directory / rel
        _write_new(path, text)
        try:
            digest = _sha256_bytes(path.read_bytes())
            self._append_ledger(
                project, 'record', ident, rel, digest,
                author=author, request_key=request_key,
            )
        except Exception:
            if path.exists():
                path.unlink()
            raise
        self._remember_id(project, ident)
        return {'id': ident, 'path': rel, 'status': status}

    def get(self, project, id_) -> dict:
        path, meta, body = self._load(project, id_)
        rel = _rel_posix(path, self.project_dir(project))
        return {
            'meta': meta,
            'body': body,
            'path': rel,
            'supersession_chain': self._chain(project, id_),
            'evidence': self._annotate_evidence(project, meta.get('evidence') or []),
        }

    @_writes
    def supersede(self, project, old_id, new_id, reason, *, author) -> dict:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('a reason is required')
        _single_line(reason, 'reason')
        if not isinstance(author, str) or not author.strip():
            raise ValueError('author is required')
        _single_line(author, 'author')
        if old_id == new_id:
            raise ValueError('a record cannot supersede itself')
        _refuse_if_flagged(reason + '\n' + author)
        old_path, old_meta, _old_body = self._load(project, old_id)
        _new_path, _new_meta, _new_body = self._load(project, new_id)
        already = old_meta.get('superseded_by')
        if old_meta.get('status') == 'superseded' and already == new_id:
            rel = _rel_posix(old_path, self.project_dir(project))
            return {
                'id': old_id,
                'new_id': new_id,
                'path': rel,
                'status': 'superseded',
                'reason': reason,
            }
        if old_meta.get('status') == 'superseded' and already and already != new_id:
            raise ValueError('record is already superseded')
        text = _read_text(old_path)
        patched = _patch_front(text, {
            'status': 'superseded',
            'superseded_by': new_id,
        })
        parsed = parse_record(patched)
        if parsed['body'] != split_record(text)[1]:
            raise ValueError('refusing to rewrite the record body')
        if parsed['meta'].get('body_sha256') != old_meta.get('body_sha256'):
            raise ValueError('supersede changed the body hash')
        folder = TYPE_DIR[old_meta['type']]
        rel = folder + '/superseded/' + old_path.name
        dest = self.project_dir(project) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() != old_path.resolve():
            _write_new(dest, patched)
            old_path.unlink()
        else:
            _write_text(dest, patched)
        digest = _sha256_bytes(dest.read_bytes())
        self._append_ledger(
            project, 'supersede', old_id, rel, digest,
            author=author, reason=reason.strip(),
        )
        return {
            'id': old_id,
            'new_id': new_id,
            'path': rel,
            'status': 'superseded',
            'reason': reason.strip(),
        }

    @_writes
    def review(self, project, id_, outcome, note, *, author, next_review_by=None) -> dict:
        if outcome not in ('confirm', 'retire'):
            raise ValueError('outcome must be confirm or retire; use supersede() to supersede')
        if not isinstance(note, str):
            raise ValueError('note must be a string')
        _single_line(note, 'note') if note else None
        if not isinstance(author, str) or not author.strip():
            raise ValueError('author is required')
        _single_line(author, 'author')
        if next_review_by is not None and (
            not isinstance(next_review_by, str) or not _DATE_RE.match(next_review_by)
        ):
            raise ValueError('next_review_by must be YYYY-MM-DD')
        _refuse_if_flagged('\n'.join([note or '', author, next_review_by or '']))
        path, meta, _body = self._load(project, id_)
        if outcome == 'confirm' and meta.get('status') != 'current':
            raise ValueError('accept the record before confirming a review')
        if outcome == 'retire' and meta.get('status') == 'superseded':
            raise ValueError('a superseded record is not retired in place')
        text = _read_text(path)
        updates = {}
        if outcome == 'retire':
            updates['status'] = 'retired'
        if outcome == 'confirm':
            if next_review_by:
                updates['review_by'] = next_review_by
            else:
                days = self._review_days(self.read_project(project), meta.get('type'))
                if days is not None:
                    updates['review_by'] = (self._now().date() + timedelta(days=int(days))).isoformat()
        if updates:
            text = _patch_front(text, updates)
        directory = self.project_dir(project)
        rel = _rel_posix(path, directory)
        if outcome == 'retire' and 'inbox' in Path(rel).parts and 'rejected' not in Path(rel).parts:
            rel = 'inbox/rejected/' + path.name
            dest = directory / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_new(dest, text)
            if path.resolve() != dest.resolve():
                path.unlink()
            path = dest
        elif updates:
            _write_text(path, text)
        rel = _rel_posix(path, directory)
        digest = _sha256_bytes(path.read_bytes())
        self._append_ledger(
            project, 'review', id_, rel, digest,
            author=author, outcome=outcome, note=note.strip() or None,
        )
        loaded = parse_record(_read_text(path))
        return {
            'id': id_,
            'path': rel,
            'status': loaded['meta'].get('status'),
            'outcome': outcome,
        }

    @_writes
    def accept(self, project, id_, *, author) -> dict:
        if not isinstance(author, str) or not author.strip():
            raise ValueError('author is required')
        _single_line(author, 'author')
        _refuse_if_flagged(author)
        path, meta, _body = self._load(project, id_)
        directory = self.project_dir(project)
        rel = _rel_posix(path, directory)
        parts = Path(rel).parts
        if 'rejected' in parts:
            raise ValueError('a rejected record is not accepted')
        if meta.get('status') == 'current' and 'inbox' not in parts:
            return {'id': id_, 'path': rel, 'status': 'current'}
        if meta.get('status') != 'proposed':
            raise ValueError('only a proposed record can be accepted')
        text = _patch_front(_read_text(path), {'status': 'current'})
        filename = path.name
        dest_rel = _dest_rel(meta['type'], 'current', filename)
        dest = directory / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_new(dest, text)
        if path.resolve() != dest.resolve():
            path.unlink()
        digest = _sha256_bytes(dest.read_bytes())
        self._append_ledger(project, 'accept', id_, dest_rel, digest, author=author)
        return {'id': id_, 'path': dest_rel, 'status': 'current'}

    @_writes
    def reject(self, project, id_, reason, *, author) -> dict:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('a reason is required')
        _single_line(reason, 'reason')
        if not isinstance(author, str) or not author.strip():
            raise ValueError('author is required')
        _single_line(author, 'author')
        _refuse_if_flagged(reason + '\n' + author)
        path, meta, _body = self._load(project, id_)
        if meta.get('status') != 'proposed':
            raise ValueError('only a proposed record can be rejected')
        directory = self.project_dir(project)
        text = _patch_front(_read_text(path), {'status': 'retired'})
        dest_rel = 'inbox/rejected/' + path.name
        dest = directory / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_new(dest, text)
        if path.resolve() != dest.resolve():
            path.unlink()
        digest = _sha256_bytes(dest.read_bytes())
        self._append_ledger(
            project, 'reject', id_, dest_rel, digest,
            author=author, reason=reason.strip(),
        )
        return {'id': id_, 'path': dest_rel, 'status': 'retired', 'reason': reason.strip()}

    def review_due(self, project, before=None) -> list:
        self.read_project(project)
        day = self._coerce_day(before)
        due = []
        for item in self.list(project, status='current'):
            review_by = item.get('review_by')
            if not review_by:
                continue
            try:
                review_day = datetime.strptime(review_by, '%Y-%m-%d').date()
            except ValueError:
                continue
            if review_day <= day:
                due.append({
                    'id': item['id'],
                    'type': item['type'],
                    'title': item['title'],
                    'status': item['status'],
                    'created': item.get('created'),
                    'review_by': review_by,
                    'path': item['path'],
                })
        due.sort(key=lambda item: (item['review_by'], item['id']))
        return due

    def list(self, project, type_=None, status='current') -> list:
        self.read_project(project)
        if type_ is not None and type_ not in TYPES:
            raise ValueError('unknown type')
        rows = []
        directory = self.project_dir(project)
        for path, text in iter_record_texts(directory):
            try:
                parsed = parse_record(text)
            except ValueError as exc:
                raise ValueError('invalid record file %s' % path.name) from exc
            meta = parsed['meta']
            if type_ is not None and meta.get('type') != type_:
                continue
            if status not in (None, 'all', '*') and meta.get('status') != status:
                continue
            rel = _rel_posix(path, directory)
            rows.append({
                'id': meta.get('id'),
                'type': meta.get('type'),
                'title': meta.get('title'),
                'status': meta.get('status'),
                'project': meta.get('project'),
                'created': meta.get('created'),
                'author': meta.get('author'),
                'review_by': meta.get('review_by'),
                'tags': list(meta.get('tags') or []),
                'sensitivity': meta.get('sensitivity'),
                'supersedes': list(meta.get('supersedes') or []),
                'superseded_by': meta.get('superseded_by'),
                'path': rel,
                'body': parsed['body'],
            })
        rows.sort(key=lambda item: (item.get('created') or '', item.get('id') or ''), reverse=True)
        return rows

    @_writes
    def regenerate(self, project) -> dict:
        """Rewrite generated Markdown. Record files are left untouched."""
        from agentbrain_contextlib.brief import build_brief

        meta = self.read_project(project)
        directory = self.project_dir(project)
        self._ensure_project_dirs(directory)
        written = {}
        brief = build_brief(self, project)
        if len(brief.encode('utf-8')) > 8192:
            raise ValueError('BRIEF.md exceeds 8192 bytes')
        targets = {
            directory / 'BRIEF.md': brief if brief.endswith('\n') else brief + '\n',
            directory / 'GLOSSARY.md': _glossary_md(self.list(project, type_='glossary', status='current')),
            directory / 'TIMELINE.md': _timeline_md(self.list(project, status=None)),
            directory / 'README.md': _project_readme(meta),
            directory / 'INDEX.md': _project_index(project, self.list(project, status=None)),
        }
        for folder in TYPE_DIR.values():
            targets[directory / folder / 'INDEX.md'] = _type_index(
                folder, self.list(project, status=None),
            )
        for path, text in targets.items():
            _write_text(path, text)
            written[_rel_posix(path, self.root)] = path.stat().st_size
        root_index = self.root / 'INDEX.md'
        root_text = _root_index(self)
        _write_text(root_index, root_text)
        written['INDEX.md'] = root_index.stat().st_size
        brief_size = (directory / 'BRIEF.md').stat().st_size
        if brief_size > 8192:
            raise ValueError('BRIEF.md exceeds 8192 bytes')
        return written

    def export(self, project, out_dir, include_private=False) -> dict:
        import zipfile

        self.read_project(project)
        directory = self.project_dir(project)
        records = []
        for path, text in iter_record_texts(directory):
            parsed = parse_record(text)
            if parsed['meta'].get('sensitivity') == 'private' and not include_private:
                continue
            rel = _rel_posix(path, directory)
            records.append((rel, path.read_bytes()))
        records.sort(key=lambda item: item[0])
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        zip_path = out / ('%s.zip' % project)
        project_bytes = (directory / 'project.json').read_bytes()
        with zipfile.ZipFile(zip_path, 'w') as archive:
            _zip_write(archive, 'project.json', project_bytes)
            for rel, data in records:
                _zip_write(archive, rel, data)
        digest = _sha256_bytes(zip_path.read_bytes())
        return {'path': str(zip_path), 'sha256': digest, 'records': len(records)}

    def import_bundle(self, bundle_path) -> dict:
        import zipfile

        bundle = Path(bundle_path)
        if not bundle.is_file():
            raise ValueError('bundle not found')
        with zipfile.ZipFile(bundle) as archive:
            names = [name for name in archive.namelist() if name and not name.endswith('/')]
            if 'project.json' not in names:
                raise ValueError('bundle is missing project.json')
            for name in names:
                if name.startswith('/') or '..' in Path(name).parts:
                    raise ValueError('bundle path escapes the project')
            try:
                meta = json.loads(archive.read('project.json').decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError('bundle project.json is invalid') from exc
            slug = meta.get('slug') if isinstance(meta, dict) else None
            if not isinstance(slug, str) or not _SLUG_RE.match(slug):
                raise ValueError('bundle project slug is invalid')
            pending = []
            for name in names:
                if name == 'project.json' or not name.endswith('.md'):
                    continue
                raw = archive.read(name)
                try:
                    text = raw.decode('utf-8')
                except UnicodeDecodeError as exc:
                    raise ValueError('bundle record is not utf-8') from exc
                if not text.startswith('---'):
                    continue
                _refuse_if_flagged(text)
                parsed = parse_record(text)
                ident = parsed['meta'].get('id')
                if not ident:
                    raise ValueError('bundle record is missing an id')
                pending.append((name, raw, parsed))
        directory = self.project_dir(slug)
        if not (directory / 'project.json').is_file():
            self._ensure_project_dirs(directory)
            _write_text(directory / 'project.json', archive_project_text(meta))
        conflicts = []
        for name, raw, parsed in pending:
            ident = parsed['meta']['id']
            existing = self._find_optional(slug, ident)
            incoming_hash = parsed['meta'].get('body_sha256')
            if existing is not None:
                _path, existing_meta, _body = existing
                if existing_meta.get('body_sha256') != incoming_hash:
                    conflicts.append(ident)
                continue
            target = directory / name
            if not _within(directory, target):
                raise ValueError('bundle path escapes the project')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            rel = _rel_posix(target, directory)
            digest = _sha256_bytes(raw)
            self._append_ledger(slug, 'import', ident, rel, digest, author=self.writer)
            self._remember_id(slug, ident)
        return {'project': slug, 'records': len(pending), 'conflicts': conflicts}

    def _now(self) -> datetime:
        clock = self.clock
        if clock is None:
            current = datetime.now(timezone.utc)
        elif callable(clock):
            current = clock()
        else:
            current = clock
        if isinstance(current, datetime):
            if current.tzinfo is None:
                return current.replace(tzinfo=timezone.utc)
            return current.astimezone(timezone.utc)
        raise ValueError('clock must return a datetime')

    def _coerce_day(self, before):
        if before is None:
            return self._now().date()
        if isinstance(before, datetime):
            return before.date()
        if isinstance(before, date):
            return before
        if isinstance(before, str):
            try:
                return datetime.strptime(before[:10], '%Y-%m-%d').date()
            except ValueError as exc:
                raise ValueError('before must be a date') from exc
        raise ValueError('before must be a date')

    def _review_days(self, project_meta: dict, type_):
        custom = project_meta.get('review_defaults') or {}
        if type_ in custom:
            return custom[type_]
        return REVIEW_DAYS.get(type_)

    def _default_status(self, project_meta, type_, author, evidence, approved_by) -> str:
        owners = set(project_meta.get('owners') or [])
        if type_ == 'fact' and evidence:
            return 'current'
        if author in owners or _is_librarian(author):
            return 'current'
        if approved_by:
            return 'current'
        return 'proposed'

    def _allocate_id(self, project, type_, when: datetime) -> str:
        taken = self._ids(project)
        for _attempt in range(12):
            ident = new_id(type_, when=when)
            if ident not in taken and ID_RE.match(ident):
                return ident
        raise ValueError('could not allocate an id')

    def _ids(self, project) -> set:
        if project not in self._id_cache:
            found = set()
            directory = self.project_dir(project)
            for _path, text in iter_record_texts(directory):
                for line in text.split('\n')[:40]:
                    if line.startswith('id:'):
                        value = line.split(':', 1)[1].strip().strip('"').strip("'")
                        found.add(value)
                        break
            self._id_cache[project] = found
        return self._id_cache[project]

    def _remember_id(self, project, ident: str) -> None:
        if project in self._id_cache:
            self._id_cache[project].add(ident)

    def _load(self, project, id_):
        found = self._find_optional(project, id_)
        if found is None:
            raise ValueError('no record %s' % id_)
        return found

    def _find_optional(self, project, id_):
        directory = self.project_dir(project)
        matches = []
        for path, text in iter_record_texts(directory):
            try:
                parsed = parse_record(text)
            except ValueError:
                continue
            if parsed['meta'].get('id') == id_:
                matches.append((path, parsed['meta'], parsed['body']))
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError('duplicate id %s' % id_)
        return matches[0]

    def _find_request(self, project, request_key):
        ledger_dir = self.project_dir(project) / '.contextlib' / 'ledger'
        if not ledger_dir.is_dir():
            return None
        found_id = None
        for path in sorted(ledger_dir.glob('*.jsonl')):
            for line in _read_text(path).splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                if obj.get('action') == 'record' and obj.get('request_key') == request_key:
                    found_id = obj.get('id')
        if not found_id:
            return None
        path, meta, _body = self._load(project, found_id)
        rel = _rel_posix(path, self.project_dir(project))
        return {'id': found_id, 'path': rel, 'status': meta.get('status')}

    def _write_lock(self, project):
        slug = self.project_dir(project).name  # validates the slug
        return _exclusive(self.root / '.contextlib' / 'locks' / ('%s.lock' % slug))

    def _append_ledger(self, project, action, ident, rel_path, file_sha, *, author=None,
                       request_key=None, reason=None, outcome=None, note=None):
        with self._write_lock(project):
            return self._append_ledger_locked(project, action, ident, rel_path, file_sha, author=author,
                                              request_key=request_key, reason=reason, outcome=outcome, note=note)

    def _append_ledger_locked(self, project, action, ident, rel_path, file_sha, *, author=None,
                              request_key=None, reason=None, outcome=None, note=None):
        directory = self.project_dir(project) / '.contextlib' / 'ledger'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ('%s.jsonl' % writer_slug(self.writer))
        prev = None
        seq = 1
        if path.exists():
            lines = [line for line in _read_text(path).splitlines() if line.strip()]
            if lines:
                last = json.loads(lines[-1])
                prev = last.get('hash')
                seq = int(last.get('seq') or len(lines)) + 1
        entry = {
            'seq': seq,
            'at': format_time(self._now()),
            'writer': self.writer,
            'action': action,
            'id': ident,
            'path': rel_path,
            'sha256': file_sha,
            'prev_hash': prev,
        }
        if author is not None:
            entry['author'] = author
        if request_key:
            entry['request_key'] = request_key
        if reason:
            entry['reason'] = reason
        if outcome:
            entry['outcome'] = outcome
        if note:
            entry['note'] = note
        entry['hash'] = ledger_hash(entry)
        with open(path, 'a', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(entry, sort_keys=True, separators=(',', ':'), ensure_ascii=False))
            handle.write('\n')
        return entry

    def _chain(self, project, start_id: str) -> list:
        rows = {item['id']: item for item in self.list(project, status=None) if item.get('id')}

        def parents(ident):
            item = rows.get(ident) or {}
            found = []
            for parent in item.get('supersedes') or []:
                if parent not in found:
                    found.append(parent)
            for other_id, other in rows.items():
                if other.get('superseded_by') == ident and other_id not in found:
                    found.append(other_id)
            return found

        def children(ident):
            item = rows.get(ident) or {}
            found = []
            successor = item.get('superseded_by')
            if successor and successor not in found:
                found.append(successor)
            for other_id, other in rows.items():
                if ident in (other.get('supersedes') or []) and other_id not in found:
                    found.append(other_id)
            return found

        seen = set()
        order = []

        def walk_back(ident):
            for parent in parents(ident):
                if parent not in seen:
                    walk_back(parent)
            if ident not in seen:
                seen.add(ident)
                order.append(ident)

        walk_back(start_id)
        queue = [start_id]
        while queue:
            current = queue.pop(0)
            for child in children(current):
                if child not in seen:
                    seen.add(child)
                    order.append(child)
                    queue.append(child)
        return order

    def _annotate_evidence(self, project, evidence) -> list:
        directory = self.project_dir(project)
        annotated = []
        for item in evidence or []:
            if not isinstance(item, dict):
                continue
            ref = item.get('ref') or ''
            pin = item.get('sha256')
            entry = {'ref': ref, 'state': 'unchecked'}
            if pin:
                entry['sha256'] = pin
            kind, _, value = ref.partition(':')
            if kind not in ('project', 'ssd'):
                annotated.append(entry)
                continue
            bases = [directory] if kind == 'project' else [self.root, directory]
            candidate = None
            for base in bases:
                probe = (base / value)
                if not _within(base, probe):
                    continue
                if probe.is_file():
                    candidate = probe
                    break
            if candidate is None:
                entry['state'] = 'missing'
            elif not pin:
                entry['state'] = 'unchecked'
            else:
                digest = _sha256_bytes(candidate.read_bytes())
                entry['state'] = 'ok' if digest == pin else 'changed'
            annotated.append(entry)
        return annotated

    def _ensure_project_dirs(self, directory: Path) -> None:
        for folder in TYPE_DIR.values():
            (directory / folder).mkdir(parents=True, exist_ok=True)
            (directory / folder / 'superseded').mkdir(exist_ok=True)
        (directory / 'inbox' / 'rejected').mkdir(parents=True, exist_ok=True)
        (directory / 'exports').mkdir(exist_ok=True)
        (directory / '.contextlib' / 'ledger').mkdir(parents=True, exist_ok=True)


def _new_library_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _normalize_evidence(evidence) -> list:
    if isinstance(evidence, str) or evidence is None:
        raise ValueError('evidence must be a list')
    items = []
    for item in evidence:
        if isinstance(item, str):
            _single_line(item, 'evidence ref')
            items.append({'ref': item})
        elif isinstance(item, dict):
            ref = item.get('ref')
            if not isinstance(ref, str):
                raise ValueError('evidence ref must be a string')
            _single_line(ref, 'evidence ref')
            cleaned = {'ref': ref}
            if item.get('sha256'):
                pin = item['sha256']
                if not isinstance(pin, str) or not re.match(r'^[0-9a-f]{64}$', pin):
                    raise ValueError('evidence sha256 must be 64 hex characters')
                cleaned['sha256'] = pin
            items.append(cleaned)
        else:
            raise ValueError('evidence item must be a string or a map')
    return items


def _normalize_ids(values, label: str) -> list:
    if isinstance(values, str) or values is None:
        raise ValueError('%s must be a list of ids' % label)
    out = []
    for item in values:
        if not isinstance(item, str) or not ID_RE.match(item):
            raise ValueError('%s must be a list of ids' % label)
        out.append(item)
    return out


def _normalize_tags(tags) -> list:
    if isinstance(tags, str) or tags is None:
        raise ValueError('tags must be a list of strings')
    out = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError('tags must be a list of strings')
        _single_line(tag, 'tag')
        out.append(tag.strip())
    return out


def _normalize_scope(scope) -> dict:
    if not isinstance(scope, dict):
        raise ValueError('scope must be a flat map')
    cleaned = {}
    for key, value in scope.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError('scope keys must be strings')
        _single_line(key, 'scope key')
        if not isinstance(value, str):
            raise ValueError('scope values must be strings')
        _single_line(value, 'scope value')
        cleaned[key] = value
    return cleaned


def _dest_rel(type_: str, status: str, filename: str) -> str:
    if status == 'proposed':
        return 'inbox/' + filename
    folder = TYPE_DIR[type_]
    if status == 'superseded':
        return folder + '/superseded/' + filename
    return folder + '/' + filename


def _within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _zip_write(archive, name: str, data: bytes) -> None:
    import zipfile
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def archive_project_text(meta: dict) -> str:
    return json.dumps(meta, indent=2, ensure_ascii=False) + '\n'


def _library_readme() -> str:
    return """# ContextLib library

This folder is a ContextLib library (`format: contextlib/1`). The Markdown files are the source of truth. A SQLite file under a project's `.contextlib/` directory is only a search index and can be rebuilt.

## How to read this in 10 minutes

1. This page.
2. `INDEX.md` — one line per project (purpose, last change, brief date).
3. `projects/<slug>/README.md` — purpose, and links to the brief, the indexes, and the glossary.
4. `projects/<slug>/BRIEF.md` — the always-loaded summary (8192 bytes or fewer).
5. `projects/<slug>/decisions/INDEX.md` — current decisions, then superseded, newest first.

The same files are what an agent reads. `index.sqlite` is disposable.

"""


def _empty_root_index() -> str:
    return """# Library index

One line per project. Last change is the newest record `created` stamp; brief date is when `BRIEF.md` was last generated.

| Project | Purpose | Last change | Brief |
| --- | --- | --- | --- |

"""


def _inbox_readme() -> str:
    return """# Inbox

Proposed records wait here for review. Accept moves a file into its type folder as `current`. Reject moves it to `inbox/rejected/`.

"""


def _project_readme(meta: dict) -> str:
    owners = meta.get('owners') or []
    owner_text = ', '.join(owners) if owners else 'none'
    purpose = meta.get('purpose') or ''
    lines = [
        '# %s' % (meta.get('name') or meta.get('slug')),
        '',
        '**Purpose:** %s' % purpose,
        '',
        '**Slug:** `%s`' % meta.get('slug'),
        '**Owners:** %s' % owner_text,
        '**Created:** %s' % (meta.get('created') or ''),
        '',
        'Start here, then read the brief, then the decision index.',
        '',
        '| Page | Why |',
        '| --- | --- |',
        '| [BRIEF.md](BRIEF.md) | Always-loaded summary (8192 bytes or fewer) |',
        '| [INDEX.md](INDEX.md) | Every current record, newest first |',
        '| [GLOSSARY.md](GLOSSARY.md) | Terms |',
        '| [TIMELINE.md](TIMELINE.md) | What landed, in order |',
        '| [decisions/INDEX.md](decisions/INDEX.md) | Current then superseded decisions |',
        '| [requirements/INDEX.md](requirements/INDEX.md) | Open requirements |',
        '| [facts/INDEX.md](facts/INDEX.md) | Key facts |',
        '| [lessons/INDEX.md](lessons/INDEX.md) | Lessons |',
        '| [glossary/INDEX.md](glossary/INDEX.md) | Glossary records |',
        '| [sources/INDEX.md](sources/INDEX.md) | Sources |',
        '| [returns/INDEX.md](returns/INDEX.md) | Returned work |',
        '| [notes/INDEX.md](notes/INDEX.md) | Brief notes |',
        '| [inbox/](inbox/) | Proposed records awaiting review |',
        '',
        'Records are append-only Markdown. Superseded files move to `superseded/` and keep a valid `body_sha256`.',
        '',
    ]
    return '\n'.join(lines)


def _md_cell(text: str) -> str:
    return (text or '').replace('|', '\\|').replace('\n', ' ')


def _link_title(text: str) -> str:
    return (text or '').replace('[', '(').replace(']', ')')


def _index_sections(rows, link_prefix='') -> str:
    current = [row for row in rows if row.get('status') == 'current']
    superseded = [row for row in rows if row.get('status') == 'superseded']
    current.sort(key=lambda row: (row.get('created') or '', row.get('id') or ''), reverse=True)
    superseded.sort(key=lambda row: (row.get('created') or '', row.get('id') or ''), reverse=True)

    def bullets(items):
        if not items:
            return ['_None._']
        lines = []
        for row in items:
            created = (row.get('created') or '')[:10]
            rel = row.get('path') or ''
            if link_prefix:
                # project index stores paths already relative to the project
                href = rel
            else:
                href = rel
            # type indexes are inside the type folder; strip the folder prefix
            lines.append('- %s [%s](%s) `%s`' % (
                created,
                _link_title(row.get('title') or ''),
                href,
                row.get('id') or '',
            ))
        return lines

    # The caller passes hrefs already adjusted.
    return current, superseded


def _bullet(row, href: str) -> str:
    created = (row.get('created') or '')[:10]
    return '- %s [%s](%s) `%s`' % (
        created,
        _link_title(row.get('title') or ''),
        href,
        row.get('id') or '',
    )


def _project_index(slug: str, rows) -> str:
    current = [row for row in rows if row.get('status') == 'current']
    superseded = [row for row in rows if row.get('status') == 'superseded']
    lines = ['# %s index' % slug, '', 'Newest first.', '', '## Current', '']
    if current:
        for row in current:
            lines.append(_bullet(row, row.get('path') or ''))
    else:
        lines.append('_None._')
    lines.extend(['', '## Superseded', ''])
    if superseded:
        for row in superseded:
            lines.append(_bullet(row, row.get('path') or ''))
    else:
        lines.append('_None._')
    lines.append('')
    return '\n'.join(lines)


_TYPE_HEADINGS = {
    'decisions': 'Decisions',
    'requirements': 'Requirements',
    'facts': 'Facts',
    'lessons': 'Lessons',
    'glossary': 'Glossary records',
    'sources': 'Sources',
    'returns': 'Returns',
    'notes': 'Brief notes',
}


def _type_index(folder: str, rows) -> str:
    prefix = folder + '/'
    super_prefix = folder + '/superseded/'
    current = []
    superseded = []
    for row in rows:
        rel = row.get('path') or ''
        if row.get('status') == 'current' and rel.startswith(prefix) and not rel.startswith(super_prefix):
            current.append(row)
        elif row.get('status') == 'superseded' and rel.startswith(super_prefix):
            superseded.append(row)
        elif row.get('status') == 'superseded' and rel.startswith(prefix):
            superseded.append(row)
    lines = ['# %s' % _TYPE_HEADINGS.get(folder, folder), '', 'Newest first.', '', '## Current', '']
    if current:
        for row in current:
            href = (row.get('path') or '')[len(prefix):]
            lines.append(_bullet(row, href))
    else:
        lines.append('_None._')
    lines.extend(['', '## Superseded', ''])
    if superseded:
        for row in superseded:
            rel = row.get('path') or ''
            href = rel[len(prefix):] if rel.startswith(prefix) else rel
            lines.append(_bullet(row, href))
    else:
        lines.append('_None._')
    lines.append('')
    return '\n'.join(lines)


def _one_line(body: str, limit: int = 240) -> str:
    text = (body or '').strip()
    match = re.search(r'\*\*Meaning:\*\*\s*(.+)', text)
    if match:
        text = match.group(1).strip()
    else:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                text = stripped
                break
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + '...'
    return text


def _glossary_md(rows) -> str:
    lines = [
        '# Glossary',
        '',
        'Generated from current `glossary` records. Newest first.',
        '',
    ]
    if not rows:
        lines.append('_None._')
        lines.append('')
        return '\n'.join(lines)
    for row in rows:
        lines.append('## %s' % (row.get('title') or 'term'))
        lines.append('')
        lines.append(_one_line(row.get('body') or ''))
        lines.append('')
        lines.append('Record: `%s`' % (row.get('id') or ''))
        lines.append('')
    return '\n'.join(lines)


def _timeline_md(rows) -> str:
    visible = [
        row for row in rows
        if row.get('status') in ('current', 'superseded', 'retired')
    ]
    lines = [
        '# Timeline',
        '',
        'Newest first.',
        '',
        '| When | Id | Type | Title |',
        '| --- | --- | --- | --- |',
    ]
    for row in visible:
        title = row.get('title') or ''
        if row.get('status') == 'superseded':
            title = '%s (superseded)' % title
        elif row.get('status') == 'retired':
            title = '%s (retired)' % title
        lines.append('| %s | %s | %s | %s |' % (
            (row.get('created') or '')[:10],
            row.get('id') or '',
            row.get('type') or '',
            _md_cell(title),
        ))
    if not visible:
        lines.append('| | | | _None._ |')
    lines.append('')
    return '\n'.join(lines)


def _root_index(library: 'Library') -> str:
    lines = [
        '# Library index',
        '',
        'One line per project. Last change is the newest record `created` stamp; brief date is when `BRIEF.md` was last generated.',
        '',
        '| Project | Purpose | Last change | Brief |',
        '| --- | --- | --- | --- |',
    ]
    projects = library.projects()
    if not projects:
        lines.append('| _None._ | | | |')
    for meta in projects:
        slug = meta.get('slug')
        try:
            rows = library.list(slug, status=None)
        except ValueError:
            rows = []
        last = ''
        for row in rows:
            created = (row.get('created') or '')[:10]
            if created > last:
                last = created
        if not last:
            last = (meta.get('created') or '')[:10] or '-'
        brief_path = library.project_dir(slug) / 'BRIEF.md'
        brief_day = '-'
        if brief_path.is_file():
            text = _read_text(brief_path)
            match = re.search(r'\*\*Generated:\*\*\s*(\d{4}-\d{2}-\d{2})', text)
            if match:
                brief_day = match.group(1)
            else:
                brief_day = datetime.fromtimestamp(brief_path.stat().st_mtime, timezone.utc).strftime('%Y-%m-%d')
        lines.append('| [%s](projects/%s/) | %s | %s | %s |' % (
            slug,
            slug,
            _md_cell(meta.get('purpose') or ''),
            last,
            brief_day,
        ))
    lines.append('')
    return '\n'.join(lines)
