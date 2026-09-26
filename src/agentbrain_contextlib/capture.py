"""Turn a RESULT.json file into a return record and proposed lessons.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agentbrain_contextlib.scanner import scan_text

__all__ = ['capture_result']


def capture_result(library, project, result_path, *, author='service:capture') -> dict:
    path = Path(result_path)
    if not path.is_file():
        raise ValueError('result file not found')
    data = path.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('result file must be utf-8 JSON') from exc
    if text.startswith('\ufeff'):
        text = text[1:]
    hits = scan_text(text)
    if hits:
        kinds = []
        for hit in hits:
            if hit.get('kind') not in kinds:
                kinds.append(hit.get('kind'))
        labels = []
        if 'secret' in kinds:
            labels.append('a secret')
        if 'abs-path' in kinds:
            labels.append('an absolute home path')
        raise ValueError('refusing to capture ' + ' and '.join(labels or ['disallowed text']))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError('result file is not JSON') from exc
    if not isinstance(payload, dict):
        raise ValueError('result file must be a JSON object')
    if not isinstance(author, str) or not author.strip():
        raise ValueError('author is required')
    evidence, digest = _pin(library, project, path, data)
    title = _text(payload, 'title') or path.stem or 'Captured result'
    title = re.sub(r'\s+', ' ', title).strip() or 'Captured result'
    user = _text(payload, 'userOutcome', 'user_outcome')
    gaps = _text(payload, 'remainingGaps', 'remaining_gaps')
    actor = _text(payload, 'nextActor', 'next_actor')
    summary = _text(payload, 'summary')
    body = _return_body(title, user, gaps, actor, summary)
    created = library.record(
        project,
        'return',
        title,
        body,
        author=author,
        evidence=(evidence,),
        status='current',
        request_key='capture:%s:return' % digest,
        tags=('capture',),
    )
    lessons = payload.get('lessons') or []
    if not isinstance(lessons, list):
        raise ValueError('lessons must be a list')
    proposed = []
    for index, lesson in enumerate(lessons):
        ltitle, lbody = _lesson(lesson)
        if not ltitle:
            continue
        rec = library.record(
            project,
            'lesson',
            ltitle,
            lbody,
            author=author,
            evidence=(evidence,),
            status='proposed',
            request_key='capture:%s:lesson:%d' % (digest, index),
            tags=('capture', 'lesson'),
        )
        proposed.append(rec['id'])
    return {'return_id': created['id'], 'proposed_ids': proposed}


def _text(payload: dict, *keys):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _return_body(title, user, gaps, actor, summary) -> str:
    lines = ['**Return:** %s' % title, '']
    if user or gaps or actor:
        if user:
            lines.append('**User outcome:** %s' % user)
            lines.append('')
        if gaps:
            lines.append('**Remaining gaps:** %s' % gaps)
            lines.append('')
        if actor:
            lines.append('**Next actor:** %s' % actor)
            lines.append('')
    elif summary:
        lines.append(summary)
        lines.append('')
    else:
        lines.append('Captured result.')
        lines.append('')
    return '\n'.join(lines)


def _lesson(lesson):
    if isinstance(lesson, str):
        text = lesson.strip()
        if not text:
            return None, None
        title = re.sub(r'\s+', ' ', text.split('\n', 1)[0]).strip()
        if len(title) > 80:
            title = title[:80].rstrip()
        body = '**Lesson:** %s\n' % text
        return title, body
    if isinstance(lesson, dict):
        title = lesson.get('title') or lesson.get('summary') or 'Lesson'
        if not isinstance(title, str):
            title = str(title)
        title = re.sub(r'\s+', ' ', title).strip() or 'Lesson'
        if len(title) > 80:
            title = title[:80].rstrip()
        body = lesson.get('body') or lesson.get('summary') or title
        if not isinstance(body, str):
            body = str(body)
        if not body.endswith('\n'):
            body += '\n'
        return title, body
    return None, None


def _pin(library, project, result_path: Path, data: bytes):
    digest = hashlib.sha256(data).hexdigest()
    directory = library.project_dir(project)
    rel = None
    try:
        rel = result_path.resolve().relative_to(directory.resolve()).as_posix()
    except ValueError:
        rel = None
    if rel and '..' not in Path(rel).parts:
        return {'ref': 'project:' + rel, 'sha256': digest}, digest
    suffix = result_path.suffix.lower() if result_path.suffix else '.json'
    if not re.match(r'^\.[a-z0-9]{1,8}$', suffix):
        suffix = '.json'
    rel = 'exports/capture-%s%s' % (digest[:16], suffix)
    dest = directory / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(data)
    return {'ref': 'project:' + rel, 'sha256': digest}, digest
