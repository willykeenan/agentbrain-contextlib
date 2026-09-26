"""Record files: a restricted front-matter parser and canonical renderer.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import date, datetime, timezone
from pathlib import Path

TYPES = (
    'decision',
    'requirement',
    'fact',
    'lesson',
    'glossary',
    'source',
    'return',
    'brief-note',
)
STATUSES = ('proposed', 'current', 'superseded', 'retired')
PREFIX = {
    'decision': 'dec',
    'requirement': 'req',
    'fact': 'fact',
    'lesson': 'les',
    'glossary': 'glo',
    'source': 'src',
    'return': 'ret',
    'brief-note': 'note',
}
TYPE_DIR = {
    'decision': 'decisions',
    'requirement': 'requirements',
    'fact': 'facts',
    'lesson': 'lessons',
    'glossary': 'glossary',
    'source': 'sources',
    'return': 'returns',
    'brief-note': 'notes',
}
REVIEW_DAYS = {
    'decision': 180,
    'requirement': None,
    'fact': 30,
    'lesson': 365,
    'glossary': 365,
    'source': 90,
    'return': None,
    'brief-note': 30,
}
SKIP_FILE_NAMES = frozenset({
    'README.md',
    'INDEX.md',
    'BRIEF.md',
    'GLOSSARY.md',
    'TIMELINE.md',
})
KEY_ORDER = (
    'id',
    'type',
    'title',
    'status',
    'project',
    'scope',
    'created',
    'author',
    'approved_by',
    'evidence',
    'supersedes',
    'superseded_by',
    'review_by',
    'tags',
    'sensitivity',
    'body_sha256',
)
ID_RE = re.compile(r'^(dec|req|fact|les|glo|src|ret|note)-(\d{8})-([0-9a-f]{4})$')
_CREATED_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_PLAIN_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+/-]*$')
_PROJECT_SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
_REQUIRED = (
    'id',
    'type',
    'title',
    'status',
    'project',
    'created',
    'author',
    'evidence',
    'supersedes',
    'superseded_by',
    'review_by',
    'tags',
    'sensitivity',
    'body_sha256',
)

__all__ = [
    'TYPES',
    'STATUSES',
    'PREFIX',
    'TYPE_DIR',
    'REVIEW_DAYS',
    'KEY_ORDER',
    'ID_RE',
    'SKIP_FILE_NAMES',
    'format_time',
    'slugify',
    'valid_evidence_ref',
    'split_record',
    'join_record',
    'parse_record',
    'render_record',
    'new_id',
    'validate',
    'body_sha256',
    'iter_record_texts',
]


def format_time(when=None) -> str:
    """UTC timestamp with a Z suffix and no fractional seconds."""
    if when is None:
        when = datetime.now(timezone.utc)
    if isinstance(when, datetime):
        current = when
    elif isinstance(when, date):
        current = datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
    else:
        raise ValueError('when must be a date or datetime')
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    return current.strftime('%Y-%m-%dT%H:%M:%SZ')


def slugify(text: str, max_len: int = 80) -> str:
    value = (text or '').lower()
    value = re.sub(r'[^a-z0-9]+', '-', value).strip('-')
    if max_len:
        value = value[:max_len].strip('-')
    return value or 'record'


def body_sha256(body: str) -> str:
    if not isinstance(body, str):
        raise ValueError('body must be a string')
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def valid_evidence_ref(ref: str) -> bool:
    """Evidence refs are project, ssd, room, https url, or note. Never absolute."""
    if not isinstance(ref, str) or ':' not in ref:
        return False
    kind, _, value = ref.partition(':')
    if not value.strip():
        return False
    if any(ch in value for ch in ('\n', '\r', '\x00')):
        return False
    if kind in ('project', 'ssd'):
        if value.startswith('/') or value.startswith('~') or value.startswith('\\'):
            return False
        if re.match(r'^[A-Za-z]:[\\/]', value):
            return False
        parts = Path(value).parts
        if '..' in parts:
            return False
        return True
    if kind == 'url':
        return value.startswith('https://') and ' ' not in value
    if kind == 'room':
        if '#' not in value:
            return False
        name, _, seq = value.partition('#')
        return bool(name) and bool(seq) and '/' not in name and '\\' not in name
    if kind == 'note':
        return True
    return False


def _strip_comment(line: str) -> str:
    in_str = False
    quote = None
    i = 0
    while i < len(line):
        char = line[i]
        if in_str:
            if quote == '"' and char == '\\' and i + 1 < len(line):
                i += 2
                continue
            if char == quote:
                in_str = False
                quote = None
            i += 1
            continue
        if char in '"\'':
            in_str = True
            quote = char
            i += 1
            continue
        if char == '#' and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index] in ' \t':
        index += 1
    return index


def _parse_quoted(text: str, index: int):
    quote = text[index]
    index += 1
    out = []
    while index < len(text):
        char = text[index]
        if quote == '"' and char == '\\' and index + 1 < len(text):
            nxt = text[index + 1]
            mapping = {'n': '\n', 't': '\t', 'r': '\r', '\\': '\\', '"': '"'}
            out.append(mapping.get(nxt, nxt))
            index += 2
            continue
        if quote == "'" and char == "'" and index + 1 < len(text) and text[index + 1] == "'":
            out.append("'")
            index += 2
            continue
        if char == quote:
            return ''.join(out), index + 1
        out.append(char)
        index += 1
    raise ValueError('unterminated string')


def _coerce_atom(token: str):
    if token == 'null':
        return None
    if token == 'true':
        return True
    if token == 'false':
        return False
    return token


def _parse_inline_list_at(text: str, index: int):
    if text[index] != '[':
        raise ValueError('not a list')
    index += 1
    index = _skip_ws(text, index)
    items = []
    if index < len(text) and text[index] == ']':
        return items, index + 1
    while index < len(text):
        index = _skip_ws(text, index)
        if index >= len(text):
            break
        if text[index] in '"\'':
            value, index = _parse_quoted(text, index)
        elif text[index] == '{':
            value, index = _parse_inline_map_at(text, index)
        elif text[index] == '[':
            value, index = _parse_inline_list_at(text, index)
        else:
            start = index
            while index < len(text) and text[index] not in ',]':
                index += 1
            value = _coerce_atom(text[start:index].strip())
        items.append(value)
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == ',':
            index += 1
            continue
        if index < len(text) and text[index] == ']':
            return items, index + 1
        raise ValueError('expected , or ] in list')
    raise ValueError('unterminated list')


def _parse_inline_map_at(text: str, index: int):
    if text[index] != '{':
        raise ValueError('not a map')
    index += 1
    index = _skip_ws(text, index)
    out = {}
    if index < len(text) and text[index] == '}':
        return out, index + 1
    while index < len(text):
        index = _skip_ws(text, index)
        if index >= len(text):
            break
        if text[index] in '"\'':
            key, index = _parse_quoted(text, index)
        else:
            match = re.match(r'[A-Za-z0-9_]+', text[index:])
            if not match:
                raise ValueError('bad map key')
            key = match.group(0)
            index += len(key)
        index = _skip_ws(text, index)
        if index >= len(text) or text[index] != ':':
            raise ValueError('expected : in map')
        index += 1
        index = _skip_ws(text, index)
        if index >= len(text):
            raise ValueError('unterminated map')
        if text[index] in '"\'':
            value, index = _parse_quoted(text, index)
        elif text[index] == '{':
            raise ValueError('nested maps are not allowed')
        elif text[index] == '[':
            value, index = _parse_inline_list_at(text, index)
        else:
            start = index
            while index < len(text) and text[index] not in ',}':
                index += 1
            value = _coerce_atom(text[start:index].strip())
        out[key] = value
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == ',':
            index += 1
            continue
        if index < len(text) and text[index] == '}':
            return out, index + 1
        raise ValueError('expected , or } in map')
    raise ValueError('unterminated map')


def parse_scalar(value: str):
    value = value.strip()
    if value == 'null':
        return None
    if value == 'true':
        return True
    if value == 'false':
        return False
    if value.startswith('['):
        items, end = _parse_inline_list_at(value, 0)
        if value[end:].strip():
            raise ValueError('trailing junk after list')
        return items
    if value.startswith('{'):
        mapping, end = _parse_inline_map_at(value, 0)
        if value[end:].strip():
            raise ValueError('trailing junk after map')
        return mapping
    if value.startswith('"') or value.startswith("'"):
        text, end = _parse_quoted(value, 0)
        if value[end:].strip():
            raise ValueError('trailing junk after string')
        return text
    return value


def parse_front_matter(block: str) -> dict:
    lines = block.split('\n')
    index = 0
    out = {}
    while index < len(lines):
        raw = lines[index]
        index += 1
        if raw.endswith('\r'):
            raw = raw[:-1]
        if not raw.strip():
            continue
        if raw.lstrip().startswith('#'):
            continue
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if line.startswith(' ') or line.startswith('\t'):
            raise ValueError('unexpected indent')
        if ':' not in line:
            raise ValueError('expected key')
        key, _, rest = line.partition(':')
        key = key.strip()
        rest = rest.strip()
        if rest == '':
            items = []
            while index < len(lines):
                nxt = lines[index]
                if nxt.endswith('\r'):
                    nxt = nxt[:-1]
                if not nxt.strip() or nxt.lstrip().startswith('#'):
                    index += 1
                    continue
                stripped = _strip_comment(nxt)
                if not (stripped.startswith(' ') or stripped.startswith('\t')):
                    break
                item = stripped.strip()
                if item.startswith('- '):
                    items.append(parse_scalar(item[2:].strip()))
                    index += 1
                elif item == '-':
                    items.append(None)
                    index += 1
                else:
                    break
            out[key] = items
        else:
            out[key] = parse_scalar(rest)
    return out


def split_record(text: str) -> tuple:
    """Split a record into ``(front_matter, body)``.

    The body is the exact text after the closing ``---`` line's newline.
    """
    if not isinstance(text, str):
        raise ValueError('record text must be a string')
    if text.startswith('\ufeff'):
        text = text[1:]
    if not text.startswith('---'):
        raise ValueError('missing opening ---')
    rest = text[3:]
    if rest.startswith('\n'):
        rest = rest[1:]
    marker = '\n---'
    end = rest.find(marker)
    if end < 0:
        raise ValueError('missing closing ---')
    front = rest[:end]
    after = rest[end + len(marker):]
    if after.startswith('\n'):
        body = after[1:]
    else:
        body = after
    return front, body


def join_record(front: str, body: str) -> str:
    if front.endswith('\n'):
        front = front[:-1]
    return '---\n' + front + '\n---\n' + body


def parse_record(text: str) -> dict:
    """Return ``{'meta': {...}, 'body': str}``. Raise ValueError on a bad file."""
    try:
        front, body = split_record(text)
        meta = parse_front_matter(front)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('bad record format') from exc
    if not isinstance(meta, dict):
        raise ValueError('bad record format')
    return {'meta': meta, 'body': body}


def _is_plain(value: str) -> bool:
    if value in ('null', 'true', 'false', 'yes', 'no'):
        return False
    return bool(_PLAIN_RE.match(value))


def _render_scalar(value):
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, str):
        if _is_plain(value):
            return value
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise ValueError('cannot render value')


def _render_inline_map(mapping: dict) -> str:
    parts = []
    for key, value in mapping.items():
        key_text = str(key)
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key_text):
            key_text = json.dumps(key_text, ensure_ascii=False)
        if isinstance(value, dict):
            raise ValueError('nested maps are not allowed')
        if isinstance(value, list):
            rendered = _render_inline_list(value)
        else:
            rendered = _render_scalar(value)
        parts.append('%s: %s' % (key_text, rendered))
    return '{' + ', '.join(parts) + '}'


def _render_inline_list(items: list) -> str:
    rendered = []
    for item in items:
        if isinstance(item, dict):
            rendered.append(_render_inline_map(item))
        elif isinstance(item, list):
            rendered.append(_render_inline_list(item))
        else:
            rendered.append(_render_scalar(item))
    return '[' + ', '.join(rendered) + ']'


def _emit(key: str, value: str) -> str:
    if isinstance(value, list) and any(isinstance(item, dict) for item in value):
        if not value:
            return '%s: []' % key
        lines = ['%s:' % key]
        for item in value:
            if isinstance(item, dict):
                lines.append('  - %s' % _render_inline_map(item))
            else:
                lines.append('  - %s' % _render_scalar(item))
        return '\n'.join(lines)
    if key == 'body_sha256' and isinstance(value, str):
        return '%s: %s' % (key, json.dumps(value, ensure_ascii=False))
    if isinstance(value, list):
        return '%s: %s' % (key, _render_inline_list(value))
    if isinstance(value, dict):
        return '%s: %s' % (key, _render_inline_map(value))
    return '%s: %s' % (key, _render_scalar(value))


def _ordered_items(meta: dict) -> list:
    data = dict(meta)
    defaults = {
        'evidence': [],
        'supersedes': [],
        'superseded_by': None,
        'review_by': None,
        'tags': [],
    }
    items = []
    seen = set()
    for key in KEY_ORDER:
        if key in ('scope', 'approved_by') and data.get(key) is None:
            continue
        if key not in data and key not in defaults:
            continue
        value = data[key] if key in data else defaults[key]
        items.append((key, value))
        seen.add(key)
    for key in sorted(data):
        if key in seen or data[key] is None:
            continue
        items.append((key, data[key]))
    return items


def render_record(meta: dict, body: str) -> str:
    """Canonical record text. Computes ``body_sha256`` from ``body``."""
    if not isinstance(meta, dict):
        raise ValueError('meta must be a map')
    if not isinstance(body, str):
        raise ValueError('body must be a string')
    data = dict(meta)
    data['body_sha256'] = body_sha256(body)
    lines = [_emit(key, value) for key, value in _ordered_items(data)]
    front = '\n'.join(lines)
    return join_record(front, body)


def _as_datetime(when):
    if when is None:
        return datetime.now(timezone.utc)
    if isinstance(when, datetime):
        current = when
    elif isinstance(when, date):
        return datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
    elif isinstance(when, str):
        text = when.strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        current = datetime.fromisoformat(text)
    else:
        raise ValueError('when must be a date, datetime, or ISO string')
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def new_id(type_: str, when=None) -> str:
    prefix = PREFIX.get(type_)
    if not prefix:
        raise ValueError('unknown type')
    current = _as_datetime(when)
    suffix = secrets.token_hex(2)
    return '%s-%s-%s' % (prefix, current.strftime('%Y%m%d'), suffix)


def _is_id(value) -> bool:
    return isinstance(value, str) and bool(ID_RE.match(value))


def validate(meta: dict, body: str) -> list:
    """Return a list of problems. An empty list means the record is valid."""
    problems = []
    if not isinstance(meta, dict):
        return ['meta must be a map']
    if not isinstance(body, str):
        return ['body must be a string']
    for key in _REQUIRED:
        if key not in meta:
            problems.append('missing %s' % key)
    type_ = meta.get('type')
    if type_ not in TYPES:
        problems.append('type is not a contextlib record type')
    status = meta.get('status')
    if status not in STATUSES:
        problems.append('status is not proposed, current, superseded, or retired')
    ident = meta.get('id')
    if not _is_id(ident):
        problems.append('id is not <prefix>-<YYYYMMDD>-<4 hex>')
    elif type_ in PREFIX and not ident.startswith(PREFIX[type_] + '-'):
        problems.append('id prefix does not match type')
    created = meta.get('created')
    if not isinstance(created, str) or not _CREATED_RE.match(created):
        problems.append('created must be YYYY-MM-DDThh:mm:ssZ')
    elif _is_id(ident) and ident.split('-')[1] != created[:10].replace('-', ''):
        problems.append('id date does not match created')
    title = meta.get('title')
    if not isinstance(title, str) or not title.strip():
        problems.append('title is required')
    elif '\n' in title or '\r' in title:
        problems.append('title must be a single line')
    project = meta.get('project')
    if not isinstance(project, str) or not _PROJECT_SLUG_RE.match(project):
        problems.append('project must be a slug')
    author = meta.get('author')
    if not isinstance(author, str) or not author.strip():
        problems.append('author is required')
    elif '\n' in author or '\r' in author:
        problems.append('author must be a single line')
    sensitivity = meta.get('sensitivity')
    if sensitivity not in ('normal', 'private'):
        problems.append('sensitivity must be normal or private')
    tags = meta.get('tags')
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        problems.append('tags must be a list of strings')
    supersedes = meta.get('supersedes')
    if not isinstance(supersedes, list) or not all(_is_id(item) for item in supersedes):
        problems.append('supersedes must be a list of ids')
    superseded_by = meta.get('superseded_by')
    if superseded_by is not None and not _is_id(superseded_by):
        problems.append('superseded_by must be an id or null')
    review_by = meta.get('review_by')
    if review_by is not None and (not isinstance(review_by, str) or not _DATE_RE.match(review_by)):
        problems.append('review_by must be YYYY-MM-DD or null')
    if 'approved_by' in meta and meta.get('approved_by') is not None:
        approved = meta.get('approved_by')
        if not isinstance(approved, str):
            problems.append('approved_by must be a string')
    scope = meta.get('scope') if 'scope' in meta else None
    if 'scope' in meta and scope is not None:
        if not isinstance(scope, dict):
            problems.append('scope must be a flat map')
        else:
            for key, value in scope.items():
                if not isinstance(key, str):
                    problems.append('scope keys must be strings')
                if isinstance(value, (dict, list)) or not isinstance(value, (str, bool, type(None))):
                    problems.append('scope values must be scalars')
    evidence = meta.get('evidence')
    if not isinstance(evidence, list):
        problems.append('evidence must be a list')
    else:
        for item in evidence:
            if not isinstance(item, dict) or 'ref' not in item:
                problems.append('evidence item must be a map with ref')
                continue
            extra = set(item) - {'ref', 'sha256'}
            if extra:
                problems.append('evidence item has unknown keys')
            if not valid_evidence_ref(item.get('ref')):
                problems.append('evidence ref is not allowed')
            pin = item.get('sha256')
            if pin is not None and (
                not isinstance(pin, str) or not re.match(r'^[0-9a-f]{64}$', pin)
            ):
                problems.append('evidence sha256 must be 64 hex characters')
    digest = body_sha256(body)
    got = meta.get('body_sha256')
    if not isinstance(got, str) or got != digest:
        problems.append('body_sha256 does not match the body')
    return problems


def iter_record_texts(root):
    """Yield ``(path, text)`` for record markdown under a project directory."""
    base = Path(root)
    if not base.exists():
        return
    for path in sorted(base.rglob('*.md')):
        if path.name in SKIP_FILE_NAMES:
            continue
        if '.contextlib' in path.parts:
            continue
        try:
            text = path.read_bytes().decode('utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        if text.startswith('\ufeff'):
            text = text[1:]
        if text.startswith('---'):
            yield path, text
