"""Stdio MCP server: newline-delimited JSON-RPC 2.0, context_* tools.

The identity is fixed for the life of serve()/handle() and is the author of
every write. Tools have no way to impersonate another writer.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agentbrain_contextlib.brief import build_brief
from agentbrain_contextlib.capture import capture_result
from agentbrain_contextlib.index import Index

__all__ = ['serve', 'handle']

PROTOCOL_VERSIONS = ('2024-11-05', '2025-03-26', '2025-06-18')
DEFAULT_PROTOCOL = '2025-06-18'
SERVER_NAME = 'contextlib'
SERVER_VERSION = '0.1.0'

_TOOLS = (
    {
        'name': 'context_brief',
        'description': 'Always-loaded project summary (at most 8192 bytes).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string', 'description': 'Project slug.'},
            },
            'required': ['project'],
        },
    },
    {
        'name': 'context_search',
        'description': 'Ranked search over the rebuildable project index.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string', 'description': 'Project slug.'},
                'query': {'type': 'string', 'description': 'Search text.'},
                'type': {'type': 'string', 'description': 'Optional record type.'},
                'status': {
                    'type': 'string',
                    'description': 'Status filter. Default current. Use all to include every status.',
                },
                'limit': {'type': 'integer', 'description': 'Maximum hits. Default 20.'},
            },
            'required': ['project', 'query'],
        },
    },
    {
        'name': 'context_get',
        'description': 'One record: meta, body, path, evidence state, supersession chain.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string', 'description': 'Project slug.'},
                'id': {'type': 'string', 'description': 'Record id.'},
            },
            'required': ['project', 'id'],
        },
    },
    {
        'name': 'context_record',
        'description': (
            'Create a record (decision, requirement, fact, lesson, glossary, '
            'source, return, brief-note). Author is the server identity.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'type': {'type': 'string'},
                'title': {'type': 'string'},
                'body': {'type': 'string'},
                'evidence': {'type': 'array'},
                'supersedes': {'type': 'array', 'items': {'type': 'string'}},
                'review_by': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'scope': {'type': 'object'},
                'tags': {'type': 'array', 'items': {'type': 'string'}},
                'sensitivity': {'type': 'string', 'enum': ['normal', 'private']},
                'approved_by': {'type': 'string'},
                'request_key': {'type': 'string'},
            },
            'required': ['project', 'type', 'title', 'body'],
        },
    },
    {
        'name': 'context_supersede',
        'description': 'Supersede an old id with a new id and move the old file.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'old_id': {'type': 'string'},
                'new_id': {'type': 'string'},
                'reason': {'type': 'string'},
            },
            'required': ['project', 'old_id', 'new_id', 'reason'],
        },
    },
    {
        'name': 'context_review_due',
        'description': 'Records whose review_by is due on or before a date (default today).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'before': {'type': 'string', 'description': 'YYYY-MM-DD. Default today.'},
            },
            'required': ['project'],
        },
    },
    {
        'name': 'context_review',
        'description': 'Confirm or retire a record. Use context_supersede to supersede.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'id': {'type': 'string'},
                'outcome': {'type': 'string', 'enum': ['confirm', 'retire']},
                'note': {'type': 'string'},
                'next_review_by': {'type': 'string', 'description': 'YYYY-MM-DD'},
            },
            'required': ['project', 'id', 'outcome'],
        },
    },
    {
        'name': 'context_capture',
        'description': 'RESULT.json becomes a return record; listed lessons go to the inbox.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'path': {'type': 'string', 'description': 'Path to RESULT.json.'},
                'result_path': {'type': 'string'},
            },
            'required': ['project'],
        },
    },
    {
        'name': 'context_export',
        'description': 'Zip a project. include_private defaults to false.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string'},
                'out_dir': {'type': 'string'},
                'include_private': {'type': 'boolean'},
            },
            'required': ['project', 'out_dir'],
        },
    },
    {
        'name': 'context_import',
        'description': 'Import a project bundle zip.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Path to the bundle zip.'},
                'bundle_path': {'type': 'string'},
            },
            'required': [],
        },
    },
    {
        'name': 'context_status',
        'description': 'Library and project health: counts, inbox, due, index age.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'project': {'type': 'string', 'description': 'Optional project slug.'},
            },
            'required': [],
        },
    },
)

_TOOL_NAMES = tuple(item['name'] for item in _TOOLS)


def serve(library, identity, stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin until EOF. Always returns 0."""
    if identity is None or not str(identity).strip():
        raise ValueError('identity is required')
    identity = str(identity).strip()
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    for raw in stdin:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode('utf-8')
            except UnicodeDecodeError:
                _write_json(stdout, {
                    'jsonrpc': '2.0',
                    'id': None,
                    'error': {'code': -32700, 'message': 'Parse error'},
                })
                continue
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write_json(stdout, {
                'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32700, 'message': 'Parse error'},
            })
            continue
        if not isinstance(message, dict):
            _write_json(stdout, {
                'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32600, 'message': 'Invalid Request'},
            })
            continue
        try:
            response = handle(library, identity, message)
        except Exception:
            if 'id' not in message:
                continue
            response = {
                'jsonrpc': '2.0',
                'id': message.get('id'),
                'error': {'code': -32603, 'message': 'Internal error'},
            }
        if response is not None:
            _write_json(stdout, response)
    return 0


def handle(library, identity, message: dict):
    """Handle one JSON-RPC message. Notifications return None."""
    if not isinstance(message, dict):
        return {
            'jsonrpc': '2.0',
            'id': None,
            'error': {'code': -32600, 'message': 'Invalid Request'},
        }
    if identity is None or not str(identity).strip():
        if 'id' not in message:
            return None
        return _rpc_error(message.get('id'), -32603, 'identity is required')
    identity = str(identity).strip()
    method = message.get('method')
    req_id = message['id'] if 'id' in message else None
    is_notification = 'id' not in message
    if not isinstance(method, str) or not method:
        if is_notification:
            return None
        return _rpc_error(req_id, -32600, 'Invalid Request')
    params = message.get('params')
    if params is None:
        params = {}
    if method in ('notifications/initialized', 'initialized', 'notifications/cancelled'):
        if is_notification:
            return None
        return _ok(req_id, {})
    if is_notification:
        return None
    if method == 'initialize':
        return _ok(req_id, _initialize(params if isinstance(params, dict) else {}))
    if method == 'ping':
        return _ok(req_id, {})
    if method == 'tools/list':
        return _ok(req_id, {'tools': [dict(tool) for tool in _TOOLS]})
    if method == 'tools/call':
        if not isinstance(params, dict):
            return _ok(req_id, _error_result('Tool arguments must be a map.'))
        return _ok(req_id, _call_tool(library, identity, params))
    return _rpc_error(req_id, -32601, 'Method not found')


def _initialize(params: dict) -> dict:
    requested = params.get('protocolVersion') or ''
    if requested in PROTOCOL_VERSIONS:
        version = requested
    else:
        version = DEFAULT_PROTOCOL
    return {
        'protocolVersion': version,
        'capabilities': {'tools': {'listChanged': False}},
        'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
        'instructions': (
            'ContextLib project library. Use context_brief first, then '
            'context_search or context_get, then context_record. Writes use '
            'the identity this server started with.'
        ),
    }


def _call_tool(library, identity, params: dict) -> dict:
    name = params.get('name')
    if not name:
        return _error_result('Tool name is required.')
    if name not in _TOOL_NAMES:
        return _error_result('Unknown tool %s.' % name)
    try:
        args = _arguments(params)
    except ValueError as exc:
        return _error_result(str(exc))
    # Identity is fixed: an author in the payload cannot impersonate another writer.
    # Status is chosen by inbox rules (same as the CLI); clients cannot force current.
    for key in ('author', 'writer', 'identity', 'status'):
        args.pop(key, None)
    try:
        result = _dispatch()[name](library, identity, args)
    except ValueError as exc:
        return _error_result(_plain(exc))
    except KeyError as exc:
        return _error_result('Missing field %s.' % exc.args[0] if exc.args else 'Missing field.')
    except Exception as exc:
        return _error_result(_plain(exc))
    if isinstance(result, str):
        text = result
    else:
        text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    return _ok_result(text)


def _dispatch() -> dict:
    return {
        'context_brief': _tool_brief,
        'context_search': _tool_search,
        'context_get': _tool_get,
        'context_record': _tool_record,
        'context_supersede': _tool_supersede,
        'context_review_due': _tool_review_due,
        'context_review': _tool_review,
        'context_capture': _tool_capture,
        'context_export': _tool_export,
        'context_import': _tool_import,
        'context_status': _tool_status,
    }


def _tool_brief(library, identity, args):
    project = _need(args, 'project')
    return build_brief(library, project)


def _tool_search(library, identity, args):
    project = _need(args, 'project')
    query = args.get('query')
    if query is None or not str(query).strip():
        raise ValueError('query is required')
    type_ = args.get('type') or args.get('type_')
    status = args.get('status', 'current')
    limit = args.get('limit', 20)
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError('limit must be an integer') from exc
    Index(library).rebuild(project)
    return Index(library).search(project, str(query), type_=type_, status=status, limit=limit)


def _tool_get(library, identity, args):
    project = _need(args, 'project')
    ident = args.get('id') or args.get('id_')
    if not ident:
        raise ValueError('id is required')
    return library.get(project, ident)


def _tool_record(library, identity, args):
    project = _need(args, 'project')
    type_ = args.get('type') or args.get('type_')
    if not type_:
        raise ValueError('type is required')
    title = args.get('title')
    if not title:
        raise ValueError('title is required')
    if 'body' not in args:
        raise ValueError('body is required')
    body = args.get('body')
    kwargs = {
        'author': identity,
        'evidence': _as_list(args.get('evidence'), empty=()),
        'supersedes': _as_list(args.get('supersedes'), empty=()),
        'tags': _as_list(args.get('tags'), empty=()),
        'sensitivity': args.get('sensitivity') or 'normal',
    }
    if args.get('review_by') is not None:
        kwargs['review_by'] = args.get('review_by')
    if args.get('scope') is not None:
        kwargs['scope'] = args.get('scope')
    if args.get('approved_by') is not None:
        kwargs['approved_by'] = args.get('approved_by')
        # An agent cannot vouch for a human: an approval quote it supplies is
        # kept for the owner to check, but the record waits in the inbox unless
        # it would have been current without that quote.
        meta = library.read_project(project)
        if library._default_status(meta, type_, identity, kwargs['evidence'], None) == 'proposed':
            kwargs['status'] = 'proposed'
    if args.get('request_key') is not None:
        kwargs['request_key'] = args.get('request_key')
    return library.record(project, type_, title, body, **kwargs)


def _tool_supersede(library, identity, args):
    project = _need(args, 'project')
    old_id = args.get('old_id') or args.get('old')
    new_id = args.get('new_id') or args.get('new')
    reason = args.get('reason')
    if not old_id:
        raise ValueError('old_id is required')
    if not new_id:
        raise ValueError('new_id is required')
    if not reason:
        raise ValueError('a reason is required')
    return library.supersede(project, old_id, new_id, reason, author=identity)


def _tool_review_due(library, identity, args):
    project = _need(args, 'project')
    before = args.get('before')
    return library.review_due(project, before=before)


def _tool_review(library, identity, args):
    project = _need(args, 'project')
    ident = args.get('id') or args.get('id_')
    outcome = args.get('outcome')
    if not ident:
        raise ValueError('id is required')
    if not outcome:
        raise ValueError('outcome is required')
    note = args.get('note')
    if note is None:
        note = ''
    kwargs = {'author': identity}
    if args.get('next_review_by') is not None:
        kwargs['next_review_by'] = args.get('next_review_by')
    return library.review(project, ident, outcome, note, **kwargs)


def _tool_capture(library, identity, args):
    project = _need(args, 'project')
    path = args.get('result_path') or args.get('path') or args.get('result')
    if not path:
        raise ValueError('path is required')
    return capture_result(library, project, path, author=identity)


def _tool_export(library, identity, args):
    project = _need(args, 'project')
    out_dir = args.get('out_dir') or args.get('output') or args.get('path')
    if not out_dir:
        raise ValueError('out_dir is required')
    include_private = bool(args.get('include_private') or False)
    return library.export(project, out_dir, include_private=include_private)


def _tool_import(library, identity, args):
    path = args.get('bundle_path') or args.get('path') or args.get('bundle')
    if not path:
        raise ValueError('path is required')
    return library.import_bundle(path)


def _tool_status(library, identity, args):
    payload = _library_meta(library)
    payload['identity'] = identity
    slug = args.get('project')
    if slug:
        payload['project'] = _project_status(library, slug)
    else:
        payload['projects'] = [_project_status(library, item['slug']) for item in library.projects()]
    return payload


def _library_meta(library) -> dict:
    root = Path(library.root)
    meta = {}
    path = root / 'library.json'
    if path.is_file():
        try:
            meta = json.loads(path.read_bytes().decode('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            meta = {}
    return {
        'format': meta.get('format'),
        'library_id': meta.get('library_id'),
        'created': meta.get('created'),
        'project_count': len(library.projects()),
    }


def _project_status(library, slug) -> dict:
    meta = library.read_project(slug)
    current = library.list(slug, status='current')
    proposed = library.list(slug, status='proposed')
    all_rows = library.list(slug, status=None)
    by_type = {}
    by_status = {}
    for row in all_rows:
        type_ = row.get('type') or 'unknown'
        status = row.get('status') or 'unknown'
        by_type[type_] = by_type.get(type_, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
    due = library.review_due(slug)
    db = library.project_dir(slug) / '.contextlib' / 'index.sqlite'
    index_age = None
    if db.is_file():
        mtime = datetime.fromtimestamp(db.stat().st_mtime, tz=timezone.utc)
        now = library._now() if hasattr(library, '_now') else datetime.now(timezone.utc)
        index_age = max(0, int((now - mtime).total_seconds()))
    return {
        'slug': meta.get('slug'),
        'name': meta.get('name'),
        'purpose': meta.get('purpose'),
        'counts': {
            'records': len(all_rows),
            'current': len(current),
            'proposed': len(proposed),
            'inbox': len(proposed),
            'review_due': len(due),
        },
        'by_type': by_type,
        'by_status': by_status,
        'inbox': len(proposed),
        'review_due': len(due),
        'index_age_seconds': index_age,
    }


def _arguments(params: dict) -> dict:
    args = params.get('arguments', params.get('args', {}))
    if args is None:
        return {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as exc:
            raise ValueError('tool arguments are not valid JSON') from exc
    if not isinstance(args, dict):
        raise ValueError('tool arguments must be a map')
    return dict(args)


def _need(args: dict, key: str) -> str:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError('%s is required' % key)
    return value


def _as_list(value, empty=None):
    if value is None:
        return [] if empty is None else empty
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _plain(exc) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = text.replace('\n', ' ').replace('\r', ' ')
    return text


def _ok(req_id, result) -> dict:
    return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def _rpc_error(req_id, code, message) -> dict:
    return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': code, 'message': message}}


def _ok_result(text: str) -> dict:
    return {
        'content': [{'type': 'text', 'text': text}],
        'isError': False,
    }


def _error_result(text: str) -> dict:
    return {
        'content': [{'type': 'text', 'text': text}],
        'isError': True,
    }


def _write_json(stdout, payload) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    try:
        stdout.flush()
    except Exception:
        pass


