"""Library doctor: plain-English checks, including the ten-minute gate.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import hashlib
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agentbrain_contextlib.index import Index
from agentbrain_contextlib.library import Library
from agentbrain_contextlib.records import REVIEW_DAYS, body_sha256, iter_record_texts, parse_record
from agentbrain_contextlib.scanner import scan_text

__all__ = ['run_doctor']

_GENERATED_RE = re.compile(r'\*\*Generated:\*\*\s*([0-9]{4}-\d{2}-\d{2}T[0-9:]+Z)')
_TEXT_SUFFIXES = {'.md', '.json', '.jsonl', '.txt'}
_BRIEF_LIMIT = 8192
_BRIEF_MAX_AGE = 30


def run_doctor(library, project=None, ten_minute=False) -> tuple:
    """Inspect a library. Returns ``(ok, lines)``.

    With ``ten_minute=True``, any of the ten-minute rules in the spec makes
    ``ok`` false. Lines are always plain English.
    """
    lines = []
    problems = []

    def note(text):
        lines.append(text)

    def problem(text):
        problems.append(text)
        lines.append(text)

    if library is None or not getattr(library, 'root', None):
        return False, ['There is no library to check.']

    root = Path(library.root)
    if project is not None:
        try:
            slugs = [library.read_project(project)['slug']]
        except ValueError:
            return False, ['There is no project %s.' % project]
    else:
        if not (root / 'README.md').is_file():
            problem('The library README.md is missing.')
        else:
            note('The library README.md is present.')
        if not (root / 'INDEX.md').is_file():
            problem('The library INDEX.md is missing.')
        else:
            note('The library INDEX.md is present.')
        slugs = [item['slug'] for item in library.projects() if item.get('slug')]
        if not slugs:
            note('The library has no projects.')

    _scan_library_root(library, note, problem)
    for slug in slugs:
        _check_project(library, slug, note, problem)

    if ten_minute:
        ok = not problems
        if ok:
            if slugs:
                note('The library can be read in ten minutes.')
            else:
                note('The empty library passes the ten-minute check.')
        else:
            note('The ten-minute check failed.')
    else:
        ok = True
        if problems:
            note('Run with --ten-minute to treat these as failures.')
        else:
            note('The library looks healthy.')
    return ok, lines


def _check_project(library, slug, note, problem) -> None:
    directory = library.project_dir(slug)
    readme = directory / 'README.md'
    brief = directory / 'BRIEF.md'
    index = directory / 'INDEX.md'
    if not readme.is_file():
        problem('README.md is missing from %s.' % slug)
    else:
        note('README.md is present in %s.' % slug)
    if not brief.is_file():
        problem('BRIEF.md is missing from %s.' % slug)
    else:
        _check_brief(library, slug, brief, note, problem)
    if not index.is_file():
        problem('INDEX.md is missing from %s.' % slug)
    else:
        note('INDEX.md is present in %s.' % slug)

    try:
        project_meta = library.read_project(slug)
    except ValueError as exc:
        problem('project.json for %s could not be read: %s' % (slug, exc))
        project_meta = {}

    current_count = 0
    inbox_count = 0
    for path, text in _safe_records(directory, problem):
        try:
            parsed = parse_record(text)
        except ValueError as exc:
            problem('Record file %s in %s could not be parsed.' % (_rel(library, path), slug))
            continue
        meta = parsed['meta']
        status = meta.get('status')
        if status == 'proposed':
            inbox_count += 1
        if status != 'current':
            continue
        current_count += 1
        ident = meta.get('id') or path.name
        title = meta.get('title') or ident
        evidence = meta.get('evidence') or []
        if not evidence:
            problem('Current record %s (%s) in %s has no evidence.' % (ident, title, slug))
        if _review_required(project_meta, meta.get('type')) and not meta.get('review_by'):
            problem('Current record %s (%s) in %s has no review date.' % (ident, title, slug))

    _scan_tree(library, directory, slug, note, problem)
    _check_index(library, slug, note, problem)
    _check_round_trip(library, slug, note, problem)
    note(
        '%s has %s current record%s and %s in the inbox.'
        % (slug, current_count, '' if current_count == 1 else 's', inbox_count)
    )


def _check_brief(library, slug, brief: Path, note, problem) -> None:
    try:
        data = brief.read_bytes()
        text = data.decode('utf-8')
    except (OSError, UnicodeDecodeError):
        problem('BRIEF.md in %s could not be read.' % slug)
        return
    size = len(data)
    if size > _BRIEF_LIMIT:
        problem('BRIEF.md in %s is %s bytes (limit %s).' % (slug, size, _BRIEF_LIMIT))
    else:
        note('BRIEF.md in %s is %s bytes.' % (slug, size))
    match = _GENERATED_RE.search(text)
    if not match:
        problem('BRIEF.md in %s has no generated date.' % slug)
        return
    generated = _parse_generated(match.group(1))
    if generated is None:
        problem('BRIEF.md in %s has no generated date.' % slug)
        return
    now = _now(library)
    age = (now.date() - generated.date()).days
    if age > _BRIEF_MAX_AGE:
        problem('BRIEF.md in %s is %s days old (limit %s days).' % (slug, age, _BRIEF_MAX_AGE))
    else:
        note('BRIEF.md in %s is %s days old.' % (slug, max(age, 0)))


def _review_required(project_meta: dict, type_) -> bool:
    defaults = (project_meta or {}).get('review_defaults') or {}
    if type_ in defaults:
        return defaults[type_] is not None
    return REVIEW_DAYS.get(type_) is not None


def _safe_records(directory: Path, problem):
    try:
        for path, text in iter_record_texts(directory):
            yield path, text
    except ValueError:
        problem('A record file under %s could not be read.' % directory.name)


def _scan_library_root(library, note, problem) -> None:
    root = Path(library.root)
    paths = []
    if root.is_dir():
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
                paths.append(path)
    _scan_paths(library, paths, 'the library', note, problem)


def _scan_tree(library, directory: Path, slug, note, problem) -> None:
    _scan_paths(library, list(_iter_text_files(directory)), slug, note, problem)


def _scan_paths(library, paths, slug, note, problem) -> None:
    hits = 0
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode('utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        found = scan_text(text)
        if not found:
            continue
        rel = _rel(library, path)
        kinds = []
        for item in found:
            kind = item.get('kind')
            line = item.get('line')
            hint = item.get('hint') or kind
            if kind == 'secret':
                problem('A secret (%s) was found in %s on line %s.' % (hint, rel, line))
            elif kind == 'abs-path':
                problem('An absolute home path was found in %s on line %s.' % (rel, line))
            else:
                problem('Disallowed text was found in %s on line %s.' % (rel, line))
            if kind not in kinds:
                kinds.append(kind)
        hits += len(found)
    if hits == 0:
        note('No secrets or absolute home paths were found in %s.' % slug)


def _iter_text_files(root: Path):
    if not root.exists():
        return
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        if '.git' in path.parts:
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        yield path


def _check_index(library, slug, note, problem) -> None:
    try:
        count = Index(library).rebuild(slug)
    except Exception:
        problem('The search index did not rebuild for %s.' % slug)
        return
    note('The search index rebuilt for %s (%s records).' % (slug, count))


def _check_round_trip(library, slug, note, problem) -> None:
    originals = {}
    directory = library.project_dir(slug)
    for path, text in _safe_records(directory, problem):
        try:
            parsed = parse_record(text)
        except ValueError:
            continue
        meta = parsed['meta']
        ident = meta.get('id')
        if not ident:
            continue
        if meta.get('sensitivity') == 'private':
            continue
        stored = meta.get('body_sha256')
        actual = body_sha256(parsed['body'])
        originals[ident] = {
            'stored': stored,
            'actual': actual,
            'body': parsed['body'],
        }
        if stored != actual:
            problem('The export/import round trip changed a hash for %s in %s.' % (ident, slug))
            return

    tmp = tempfile.TemporaryDirectory()
    try:
        out_dir = Path(tmp.name) / 'export'
        try:
            exported = library.export(slug, out_dir, include_private=False)
        except Exception:
            problem('The export/import round trip failed for %s.' % slug)
            return
        fresh_root = Path(tmp.name) / 'fresh'
        try:
            fresh = Library.init(fresh_root, clock=getattr(library, 'clock', None), writer='doctor')
            result = fresh.import_bundle(exported['path'])
        except Exception:
            problem('The export/import round trip failed for %s.' % slug)
            return
        if result.get('conflicts'):
            problem('The export/import round trip changed a hash in %s.' % slug)
            return
        for ident, snap in originals.items():
            try:
                imported = fresh.get(result.get('project') or slug, ident)
            except ValueError:
                problem('The export/import round trip changed a hash for %s in %s.' % (ident, slug))
                return
            new_actual = hashlib.sha256(imported['body'].encode('utf-8')).hexdigest()
            new_stored = imported['meta'].get('body_sha256')
            if (
                new_actual != snap['actual']
                or new_stored != snap['stored']
                or imported['body'] != snap['body']
            ):
                problem('The export/import round trip changed a hash for %s in %s.' % (ident, slug))
                return
    finally:
        tmp.cleanup()
    note('The export/import round trip kept every hash in %s.' % slug)


def _rel(library, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(library.root).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _now(library) -> datetime:
    getter = getattr(library, '_now', None)
    if callable(getter):
        current = getter()
        if isinstance(current, datetime):
            if current.tzinfo is None:
                return current.replace(tzinfo=timezone.utc)
            return current.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _parse_generated(value: str):
    text = (value or '').strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(text)
    except ValueError:
        return None
