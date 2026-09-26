#!/usr/bin/env python3
"""Export examples/sample-library to space/library.json for the static Space.

Standard library only. Uses the core Library API: projects(), list(), get(),
and project_dir() for BRIEF.md. Run from any working directory:

    python3 space/build.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SPACE_DIR = Path(__file__).resolve().parent
ROOT = SPACE_DIR.parent
SRC = ROOT / 'src'
SAMPLE = ROOT / 'examples' / 'sample-library'
OUT = SPACE_DIR / 'library.json'


def _load_library(root: Path):
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from agentbrain_contextlib.library import Library
    return Library(root)


def export_payload(library_root=None) -> dict:
    """Build the JSON payload from a ContextLib library root."""
    root = Path(library_root or SAMPLE)
    lib = _load_library(root)
    library_meta_path = root / 'library.json'
    if not library_meta_path.is_file():
        raise SystemExit('no library.json under %s' % root)
    library_meta = json.loads(library_meta_path.read_text(encoding='utf-8'))
    projects = []
    for project in lib.projects():
        slug = project.get('slug')
        if not slug:
            continue
        brief_path = lib.project_dir(slug) / 'BRIEF.md'
        if brief_path.is_file():
            brief = brief_path.read_bytes().decode('utf-8')
        else:
            brief = ''
        records = []
        for item in lib.list(slug, status=None):
            ident = item.get('id')
            if not ident:
                continue
            got = lib.get(slug, ident)
            records.append({
                'meta': got['meta'],
                'body': got['body'],
                'path': got['path'],
                'supersession_chain': list(got.get('supersession_chain') or []),
            })
        projects.append({
            'meta': project,
            'brief': brief,
            'records': records,
        })
    return {
        'format': 'contextlib/1',
        'library': library_meta,
        'projects': projects,
    }


def dumps(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + '\n'


def write_library_json(library_root=None, out_path=None) -> Path:
    dest = Path(out_path or OUT)
    text = dumps(export_payload(library_root))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    return dest


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    library_root = argv[0] if len(argv) >= 1 else None
    out_path = argv[1] if len(argv) >= 2 else None
    path = write_library_json(library_root, out_path)
    print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
