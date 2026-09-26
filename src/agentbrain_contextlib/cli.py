"""ctxlib: the ContextLib command line.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from agentbrain_contextlib.brief import build_brief
from agentbrain_contextlib.index import Index
from agentbrain_contextlib.library import Library
from agentbrain_contextlib.records import TYPES, render_record

__all__ = ['main']


class _Parser(argparse.ArgumentParser):
    """One plain line on error; never dump a usage block or traceback."""

    def error(self, message):
        raise SystemExit(message)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        handler = getattr(args, 'handler', None)
        if handler is None:
            parser.error('a command is required')
        result = handler(args)
        return int(result or 0)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, str):
            line = code.strip().splitlines()[0] if code.strip() else 'error'
            sys.stderr.write(line + '\n')
            return 1
        try:
            return int(code)
        except (TypeError, ValueError):
            return 1
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        sys.stderr.write(message.splitlines()[0] + '\n')
        return 1


def build_parser() -> _Parser:
    parser = _Parser(
        prog='ctxlib',
        description='ContextLib: a project library that outlives every agent session.',
    )
    parser.add_argument(
        '--library',
        metavar='PATH',
        help='library root (else CONTEXTLIB_ROOT, else ~/ContextLib)',
    )
    sub = parser.add_subparsers(dest='command', metavar='COMMAND', required=True, parser_class=_Parser)

    init = sub.add_parser('init', help='create a library (and optionally the first project)')
    init.add_argument('path', metavar='PATH')
    init.add_argument('--project', metavar='SLUG')
    init.add_argument('--name', metavar='NAME')
    init.add_argument('--purpose', metavar='TEXT', default='')
    init.set_defaults(handler=cmd_init)

    project = sub.add_parser('project', help='add or list projects')
    project_sub = project.add_subparsers(dest='project_cmd', metavar='ACTION', required=True, parser_class=_Parser)
    project_add = project_sub.add_parser('add', help='add a project folder')
    project_add.add_argument('slug', metavar='SLUG')
    project_add.add_argument('name', metavar='NAME')
    project_add.add_argument('--purpose', metavar='TEXT', default='')
    project_add.set_defaults(handler=cmd_project_add)
    project_list = project_sub.add_parser('list', help='list projects')
    project_list.set_defaults(handler=cmd_project_list)

    add = sub.add_parser('add', help='write a record')
    add.add_argument('project', metavar='PROJECT')
    add.add_argument('type_', metavar='TYPE', choices=TYPES)
    add.add_argument('title', metavar='TITLE')
    body = add.add_mutually_exclusive_group(required=True)
    body.add_argument('--body', metavar='TEXT')
    body.add_argument('--body-file', metavar='F', dest='body_file')
    add.add_argument('--author', metavar='ID', required=True)
    add.add_argument('--evidence', metavar='REF', action='append', default=None)
    add.add_argument('--tag', metavar='T', action='append', default=None)
    add.add_argument('--review-by', metavar='DATE', dest='review_by')
    add.add_argument('--approved-by', metavar='TEXT', dest='approved_by')
    add.set_defaults(handler=cmd_add)

    get = sub.add_parser('get', help='print one record')
    get.add_argument('project', metavar='PROJECT')
    get.add_argument('record_id', metavar='ID')
    get.set_defaults(handler=cmd_get)

    search = sub.add_parser('search', help='search the rebuildable index')
    search.add_argument('project', metavar='PROJECT')
    search.add_argument('query', metavar='QUERY')
    search.add_argument('--type', dest='type_', metavar='TYPE', choices=TYPES)
    search.add_argument('--all', action='store_true')
    search.set_defaults(handler=cmd_search)

    brief = sub.add_parser('brief', help='print the always-loaded summary')
    brief.add_argument('project', metavar='PROJECT')
    brief.set_defaults(handler=cmd_brief)

    supersede = sub.add_parser('supersede', help='mark old superseded by new')
    supersede.add_argument('project', metavar='PROJECT')
    supersede.add_argument('old_id', metavar='OLD')
    supersede.add_argument('new_id', metavar='NEW')
    supersede.add_argument('--reason', metavar='TEXT', required=True)
    supersede.add_argument('--author', metavar='ID', required=True)
    supersede.set_defaults(handler=cmd_supersede)

    review = sub.add_parser('review', help='confirm or retire a record')
    review.add_argument('project', metavar='PROJECT')
    review.add_argument('record_id', metavar='ID')
    review.add_argument('outcome', choices=('confirm', 'retire'))
    review.add_argument('--note', metavar='TEXT', required=True)
    review.add_argument('--author', metavar='ID', required=True)
    review.set_defaults(handler=cmd_review)

    inbox = sub.add_parser('inbox', help='list proposed records')
    inbox.add_argument('project', metavar='PROJECT')
    inbox.set_defaults(handler=cmd_inbox)

    accept = sub.add_parser('accept', help='move inbox to current')
    accept.add_argument('project', metavar='PROJECT')
    accept.add_argument('record_id', metavar='ID')
    accept.add_argument('--author', metavar='ID', required=True)
    accept.set_defaults(handler=cmd_accept)

    reject = sub.add_parser('reject', help='move inbox to rejected')
    reject.add_argument('project', metavar='PROJECT')
    reject.add_argument('record_id', metavar='ID')
    reject.add_argument('--reason', metavar='TEXT', required=True)
    reject.add_argument('--author', metavar='ID', required=True)
    reject.set_defaults(handler=cmd_reject)

    due = sub.add_parser('due', help='records whose review_by is due')
    due.add_argument('project', metavar='PROJECT')
    due.set_defaults(handler=cmd_due)

    regen = sub.add_parser('regen', help='rewrite BRIEF, INDEX, GLOSSARY, TIMELINE, README')
    regen.add_argument('project', metavar='PROJECT', nargs='?')
    regen.add_argument('--all', action='store_true', dest='all_projects')
    regen.set_defaults(handler=cmd_regen)

    rebuild = sub.add_parser('rebuild', help='rebuild the SQLite search index from files')
    rebuild.set_defaults(handler=cmd_rebuild)

    capture = sub.add_parser('capture', help='RESULT.json to a return record')
    capture.add_argument('project', metavar='PROJECT')
    capture.add_argument('result', metavar='RESULT.json')
    capture.set_defaults(handler=cmd_capture)

    import_md = sub.add_parser('import-md', help='Markdown file to a record')
    import_md.add_argument('project', metavar='PROJECT')
    import_md.add_argument('path', metavar='FILE')
    import_md.add_argument('--type', dest='type_', metavar='TYPE', required=True, choices=TYPES)
    import_md.add_argument('--author', metavar='ID', required=True)
    import_md.set_defaults(handler=cmd_import_md)

    export = sub.add_parser('export', help='zip a project')
    export.add_argument('project', metavar='PROJECT')
    export.add_argument('out_dir', metavar='OUT_DIR')
    export.add_argument('--include-private', action='store_true', dest='include_private')
    export.set_defaults(handler=cmd_export)

    bundle = sub.add_parser('import', help='import a zip')
    bundle.add_argument('bundle', metavar='BUNDLE')
    bundle.set_defaults(handler=cmd_import)

    doctor = sub.add_parser('doctor', help='plain-English health check')
    doctor.add_argument('project', metavar='PROJECT', nargs='?')
    doctor.add_argument('--ten-minute', action='store_true', dest='ten_minute')
    doctor.set_defaults(handler=cmd_doctor)

    sync = sub.add_parser('sync', help='git pull/push when the library is a git repo')
    sync.set_defaults(handler=cmd_sync)

    mcp = sub.add_parser('mcp', help='stdio MCP server')
    mcp.add_argument('--identity', metavar='ID', required=True)
    mcp.set_defaults(handler=cmd_mcp)

    return parser


def _expand(path) -> Path:
    return Path(path).expanduser()


def _library_root(args) -> Path:
    if getattr(args, 'library', None):
        return _expand(args.library)
    env = os.environ.get('CONTEXTLIB_ROOT')
    if env:
        return _expand(env)
    return Path.home() / 'ContextLib'


def _open_library(args) -> Library:
    return Library(_library_root(args))


def _print_write(result: dict) -> None:
    print('id: %s' % result.get('id', ''))
    print('path: %s' % result.get('path', ''))
    print('status: %s' % result.get('status', ''))


def _read_body(args) -> str:
    if args.body is not None:
        return args.body
    path = _expand(args.body_file)
    if not path.is_file():
        raise ValueError('body file not found')
    try:
        return path.read_bytes().decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('body file must be utf-8') from exc


def cmd_init(args):
    if args.project and not args.name:
        raise ValueError('--name is required with --project')
    root = _expand(args.path)
    library = Library.init(root)
    print('initialized %s' % library.root)
    if args.project:
        library.create_project(args.project, args.name, purpose=args.purpose or '')
        print('created project %s' % args.project)
    return 0


def cmd_project_add(args):
    library = _open_library(args)
    library.create_project(args.slug, args.name, purpose=args.purpose or '')
    print('created project %s' % args.slug)
    return 0


def cmd_project_list(args):
    library = _open_library(args)
    rows = library.projects()
    if not rows:
        print('no projects')
        return 0
    for item in rows:
        print('%s\t%s\t%s' % (item.get('slug') or '', item.get('name') or '', item.get('purpose') or ''))
    return 0


def cmd_add(args):
    library = _open_library(args)
    result = library.record(
        args.project,
        args.type_,
        args.title,
        _read_body(args),
        author=args.author,
        evidence=args.evidence or (),
        tags=args.tag or (),
        review_by=args.review_by,
        approved_by=args.approved_by,
    )
    _print_write(result)
    return 0


def cmd_get(args):
    library = _open_library(args)
    got = library.get(args.project, args.record_id)
    text = render_record(got['meta'], got['body'])
    sys.stdout.write(text if text.endswith('\n') else text + '\n')
    print('path: %s' % got['path'])
    chain = got.get('supersession_chain') or []
    print('supersession_chain: %s' % ', '.join(chain))
    for item in got.get('evidence') or []:
        print('evidence: %s %s' % (item.get('ref') or '', item.get('state') or ''))
    return 0


def cmd_search(args):
    library = _open_library(args)
    index = Index(library)
    index.rebuild(args.project)
    status = 'all' if args.all else 'current'
    hits = index.search(args.project, args.query, type_=args.type_, status=status)
    if not hits:
        print('no matches')
        return 0
    for hit in hits:
        print('%s\t%s\t%s\t%s' % (hit.get('id') or '', hit.get('type') or '', hit.get('status') or '', hit.get('title') or ''))
        snippet = (hit.get('snippet') or '').replace('\n', ' ').strip()
        if snippet:
            print('  %s' % snippet)
    return 0


def cmd_brief(args):
    library = _open_library(args)
    text = build_brief(library, args.project)
    sys.stdout.write(text if text.endswith('\n') else text + '\n')
    return 0


def cmd_supersede(args):
    library = _open_library(args)
    result = library.supersede(
        args.project, args.old_id, args.new_id, args.reason, author=args.author,
    )
    _print_write(result)
    print('new_id: %s' % result.get('new_id', ''))
    return 0


def cmd_review(args):
    library = _open_library(args)
    result = library.review(
        args.project, args.record_id, args.outcome, args.note, author=args.author,
    )
    _print_write(result)
    print('outcome: %s' % result.get('outcome', ''))
    return 0


def cmd_inbox(args):
    library = _open_library(args)
    rows = library.list(args.project, status='proposed')
    if not rows:
        print('inbox is empty')
        return 0
    for item in rows:
        print('%s\t%s\t%s\t%s' % (item.get('id') or '', item.get('type') or '', item.get('title') or '', item.get('path') or ''))
    return 0


def cmd_accept(args):
    library = _open_library(args)
    result = library.accept(args.project, args.record_id, author=args.author)
    _print_write(result)
    return 0


def cmd_reject(args):
    library = _open_library(args)
    result = library.reject(args.project, args.record_id, args.reason, author=args.author)
    _print_write(result)
    return 0


def cmd_due(args):
    library = _open_library(args)
    rows = library.review_due(args.project)
    if not rows:
        print('nothing is due')
        return 0
    for item in rows:
        print('%s\t%s\t%s\t%s' % (item.get('id') or '', item.get('type') or '', item.get('review_by') or '', item.get('title') or ''))
    return 0


def cmd_regen(args):
    if args.all_projects and args.project:
        raise ValueError('regen takes a project or --all')
    if not args.all_projects and not args.project:
        raise ValueError('regen requires a project or --all')
    library = _open_library(args)
    if args.all_projects:
        slugs = [item['slug'] for item in library.projects()]
        if not slugs:
            print('no projects')
            return 0
    else:
        slugs = [args.project]
    for slug in slugs:
        sizes = library.regenerate(slug)
        print('regenerated %s' % slug)
        for rel in sorted(sizes):
            print('%s %s' % (rel, sizes[rel]))
    return 0


def cmd_rebuild(args):
    library = _open_library(args)
    count = Index(library).rebuild()
    print('rebuilt %s records' % count)
    return 0


def cmd_capture(args):
    from agentbrain_contextlib.importers import import_result

    library = _open_library(args)
    result = import_result(library, args.project, _expand(args.result))
    print('return_id: %s' % result.get('return_id', ''))
    proposed = result.get('proposed_ids') or []
    print('proposed_ids: %s' % ', '.join(proposed))
    return 0


def cmd_import_md(args):
    from agentbrain_contextlib.importers import import_markdown

    library = _open_library(args)
    result = import_markdown(library, args.project, _expand(args.path), args.type_, args.author)
    _print_write(result)
    return 0


def cmd_export(args):
    library = _open_library(args)
    result = library.export(args.project, _expand(args.out_dir), include_private=args.include_private)
    print('path: %s' % result.get('path', ''))
    print('sha256: %s' % result.get('sha256', ''))
    print('records: %s' % result.get('records', ''))
    return 0


def cmd_import(args):
    library = _open_library(args)
    result = library.import_bundle(_expand(args.bundle))
    print('project: %s' % result.get('project', ''))
    print('records: %s' % result.get('records', ''))
    conflicts = result.get('conflicts') or []
    print('conflicts: %s' % (', '.join(conflicts) if conflicts else 'none'))
    return 0


def cmd_doctor(args):
    from agentbrain_contextlib.doctor import run_doctor

    library = _open_library(args)
    ok, lines = run_doctor(library, project=args.project, ten_minute=args.ten_minute)
    for line in lines or []:
        print(line)
    return 0 if ok else 1


def cmd_sync(args):
    root = _library_root(args)
    if not (root / '.git').exists():
        print('Library is not a git repository; sync is a no-op.')
        return 0
    _run_git(root, 'pull', '--ff-only')
    _run_git(root, 'push')
    print('synced')
    return 0


def cmd_mcp(args):
    from agentbrain_contextlib.mcp import serve

    library = _open_library(args)
    code = serve(library, args.identity)
    return 0 if code is None else int(code)


_GIT_ISOLATE = (
    'GIT_DIR',
    'GIT_WORK_TREE',
    'GIT_INDEX_FILE',
    'GIT_OBJECT_DIRECTORY',
    'GIT_ALTERNATE_OBJECT_DIRECTORIES',
    'GIT_COMMON_DIR',
)


def _run_git(root: Path, *action: str) -> None:
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    for key in _GIT_ISOLATE:
        env.pop(key, None)
    try:
        completed = subprocess.run(
            ['git', '-C', str(root), *action],
            check=False,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise ValueError('git is not installed') from None
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or '').strip().splitlines()
        action_name = action[0] if action else 'command'
        if detail:
            raise ValueError('git %s failed: %s' % (action_name, detail[0].strip()))
        raise ValueError('git %s failed' % action_name)


if __name__ == '__main__':
    sys.exit(main())
