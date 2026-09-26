"""Turn a Markdown file or a RESULT.json into library records.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

from pathlib import Path

from agentbrain_contextlib.capture import capture_result

__all__ = ['import_markdown', 'import_result']


def import_markdown(library, project, path, type_, author) -> dict:
    """Create a record from a Markdown file.

    The first ``# `` heading is the title; otherwise the file stem is used.
    Returns the same dict as ``Library.record``.
    """
    source = Path(path).expanduser()
    if not source.is_file():
        raise ValueError('markdown file not found')
    try:
        text = source.read_bytes().decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('markdown file must be utf-8') from exc
    if text.startswith('\ufeff'):
        text = text[1:]
    title, body = _title_and_body(text, source.stem)
    return library.record(project, type_, title, body, author=author)


def import_result(library, project, path, author='service:capture') -> dict:
    """Thin wrapper over ``capture.capture_result``."""
    return capture_result(library, project, Path(path).expanduser(), author=author)


def _title_and_body(text: str, fallback: str):
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith('# '):
            continue
        heading = line[2:].strip()
        if not heading:
            continue
        rest = lines[index + 1:]
        if rest and rest[0] == '':
            rest = rest[1:]
        body = '\n'.join(rest)
        if body and not body.endswith('\n'):
            body += '\n'
        return heading, body
    body = text
    if body and not body.endswith('\n'):
        body += '\n'
    title = (fallback or '').strip() or 'untitled'
    return title, body
