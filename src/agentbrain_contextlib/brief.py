"""Always-loaded project brief. The rendered text is at most 8192 bytes.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import re

from agentbrain_contextlib.records import format_time

__all__ = ['build_brief']

_LIMIT = 8192


def build_brief(library, project) -> str:
    meta = library.read_project(project)
    generated = format_time(library._now())
    day = generated[:10]
    current = library.list(project, status='current')
    due = library.review_due(project)
    # Newest first, so the records a reader most likely needs survive trimming.
    current = sorted(current, key=lambda row: (str(row.get('created') or ''), str(row.get('id') or '')), reverse=True)
    groups = {
        'decision': [row for row in current if row.get('type') == 'decision'],
        'requirement': [row for row in current if row.get('type') == 'requirement'],
        'fact': [row for row in current if row.get('type') == 'fact'],
        'return': [row for row in current if row.get('type') == 'return'],
        'glossary': [row for row in current if row.get('type') == 'glossary'],
    }
    groups['glossary'].sort(key=lambda row: str(row.get('title') or '').lower())
    future = []
    for row in current:
        review_by = row.get('review_by')
        if review_by and review_by > day:
            future.append(review_by)
    next_review = min(future) if future else None
    # Start generous and shrink the largest section until the brief fits in
    # 8 KB, so small projects show everything and large ones stay bounded.
    budgets = {
        'decision': min(len(groups['decision']), 40),
        'requirement': min(len(groups['requirement']), 25),
        'fact': min(len(groups['fact']), 25),
        'return': min(len(groups['return']), 8),
        'glossary': min(len(groups['glossary']), 15),
    }
    while True:
        text = _compose(meta, generated, day, groups, budgets, len(due), next_review)
        if len(text.encode('utf-8')) <= _LIMIT:
            return text
        key = max(budgets, key=lambda name: budgets[name])
        if budgets[key] > 0:
            budgets[key] -= 1
            continue
        return _hard_trim(text)


def _compose(meta, generated, day, groups, budgets, due_count, next_review) -> str:
    name = _clip(meta.get('name') or meta.get('slug') or 'project', 120)
    purpose = _clip(re.sub(r'\s+', ' ', (meta.get('purpose') or '').strip()), 500)
    lines = [
        '# %s' % name,
        '',
        '**Purpose:** %s' % purpose,
        '',
        '**Generated:** %s' % generated,
        '',
        '## Current decisions',
        '',
    ]
    lines.extend(_bullets(groups['decision'], budgets['decision'], with_title=True))
    lines.extend(['', '## Open requirements', ''])
    lines.extend(_bullets(groups['requirement'], budgets['requirement'], with_title=True))
    lines.extend(['', '## Key facts', ''])
    lines.extend(_bullets(groups['fact'], budgets['fact'], with_title=False))
    lines.extend(['', '## Recent returns', ''])
    lines.extend(_bullets(groups['return'], budgets['return'], with_title=True))
    noun = 'record' if due_count == 1 else 'records'
    lines.extend([
        '',
        '## Review due',
        '',
        '%d %s due on or before %s.' % (due_count, noun, day),
    ])
    if next_review:
        lines.append('Next review %s.' % next_review)
    lines.extend(['', '## Glossary (short)', ''])
    lines.extend(_bullets(groups['glossary'], budgets['glossary'], with_title=True))
    lines.append('')
    return '\n'.join(lines)


def _bullets(rows, budget, with_title: bool) -> list:
    if budget <= 0 or not rows:
        return ['_None._']
    shown = rows[:budget]
    lines = []
    for row in shown:
        title = _clip(re.sub(r'\s+', ' ', (row.get('title') or '').strip()), 80)
        blurb = _clip(_excerpt(row.get('body') or ''), 120)
        if with_title:
            if blurb:
                lines.append('- **%s** — %s' % (title, blurb))
            else:
                lines.append('- **%s**' % title)
        else:
            text = blurb or title
            lines.append('- %s' % text)
    extra = len(rows) - len(shown)
    if extra > 0:
        lines.append('- + %d more' % extra)
    return lines


def _excerpt(body: str) -> str:
    text = body.strip()
    match = re.search(r'\*\*Meaning:\*\*\s*(.+)', text)
    if match:
        text = match.group(1)
    else:
        for line in text.splitlines():
            stripped = re.sub(r'\*\*', '', line).strip()
            if stripped:
                text = stripped
                break
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 3].rstrip() + '...'


def _hard_trim(text: str) -> str:
    raw = text.encode('utf-8')
    if len(raw) <= _LIMIT:
        return text
    trimmed = raw[:_LIMIT]
    while trimmed:
        try:
            decoded = trimmed.decode('utf-8')
            break
        except UnicodeDecodeError:
            trimmed = trimmed[:-1]
    else:
        decoded = ''
    if '\n' in decoded:
        decoded = decoded[:decoded.rfind('\n') + 1]
    if len(decoded.encode('utf-8')) > _LIMIT:
        decoded = ''
    return decoded
