"""Rebuildable SQLite index. The Markdown files remain the source of truth.

Apache-2.0, copyright KE Studios.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from agentbrain_contextlib.records import iter_record_texts, parse_record

__all__ = ['Index']


class Index:
    def __init__(self, library):
        self.library = library

    def rebuild(self, project=None) -> int:
        if project is None:
            total = 0
            for meta in self.library.projects():
                total += self._rebuild_one(meta['slug'])
            return total
        self.library.read_project(project)
        return self._rebuild_one(project)

    def search(self, project, query, type_=None, status='current', limit=20) -> list:
        self.library.read_project(project)
        if not query or not str(query).strip():
            return []
        if limit is None:
            limit = 20
        if limit <= 0:
            return []
        path = self._db_path(project)
        if not path.is_file():
            return []
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            clauses = []
            params = []
            if type_:
                clauses.append('type = ?')
                params.append(type_)
            if status not in (None, 'all', '*'):
                clauses.append('status = ?')
                params.append(status)
            sql = 'SELECT id, type, title, status, created, path, body FROM records'
            if clauses:
                sql += ' WHERE ' + ' AND '.join(clauses)
            rows = list(conn.execute(sql, params))
            fts_ids = _fts_hits(conn, query)
        finally:
            conn.close()
        ranked = []
        for row in rows:
            score = _score(row['title'] or '', row['body'] or '', query)
            if row['id'] in fts_ids:
                score += 1
            if score <= 0:
                continue
            created = row['created'] or ''
            ranked.append({
                'id': row['id'],
                'type': row['type'],
                'title': row['title'],
                'status': row['status'],
                'date': created[:10],
                'path': row['path'],
                'snippet': _snippet(row['title'] or '', row['body'] or '', query),
                '_score': score,
                '_created': created,
            })
        ranked.sort(key=lambda item: (-item['_score'], item['_created'], item['id']), reverse=False)
        # created should be newest first when scores tie, so sort created descending.
        ranked.sort(key=lambda item: (-item['_score'], _invert_time(item['_created']), item['id']))
        results = []
        for item in ranked[:limit]:
            results.append({
                'id': item['id'],
                'type': item['type'],
                'title': item['title'],
                'status': item['status'],
                'date': item['date'],
                'path': item['path'],
                'snippet': item['snippet'],
            })
        return results

    def _db_path(self, project) -> Path:
        return self.library.project_dir(project) / '.contextlib' / 'index.sqlite'

    def _rebuild_one(self, project) -> int:
        directory = self.library.project_dir(project)
        rows = []
        for path, text in iter_record_texts(directory):
            try:
                parsed = parse_record(text)
            except ValueError as exc:
                raise ValueError('invalid record file %s' % path.name) from exc
            meta = parsed['meta']
            ident = meta.get('id')
            if not ident:
                continue
            rel = path.resolve().relative_to(directory.resolve()).as_posix()
            rows.append((
                ident,
                meta.get('type') or '',
                meta.get('title') or '',
                meta.get('status') or '',
                meta.get('created') or '',
                rel,
                parsed['body'],
            ))
        db = self._db_path(project)
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db))
        try:
            conn.execute('DROP TABLE IF EXISTS records_fts')
            conn.execute('DROP TABLE IF EXISTS records')
            conn.execute(
                '''
                CREATE TABLE records (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created TEXT NOT NULL,
                    path TEXT NOT NULL,
                    body TEXT NOT NULL
                )
                '''
            )
            conn.executemany(
                'INSERT INTO records (id, type, title, status, created, path, body) VALUES (?, ?, ?, ?, ?, ?, ?)',
                rows,
            )
            conn.commit()
            try:
                _fill_fts(conn, rows)
                conn.commit()
            except sqlite3.OperationalError:
                conn.rollback()
        finally:
            conn.close()
        return len(rows)


def _invert_time(value: str) -> str:
    # Lexicographic ISO timestamps sort newest-last; invert by complement is unnecessary
    # if we prefix a descending key. Empty created sorts last among ties.
    return ''.join(chr(255 - ord(ch)) if ord(ch) < 256 else ch for ch in (value or ''))


def _score(title: str, body: str, query: str) -> int:
    needle = query.casefold().strip()
    if not needle:
        return 0
    title_fold = title.casefold()
    body_fold = body.casefold()
    score = 0
    if needle in title_fold:
        score += 100
    if needle in body_fold:
        score += 20
    for word in needle.split():
        if word in title_fold:
            score += 10
        if word in body_fold:
            score += 2
    return score


def _snippet(title: str, body: str, query: str, limit: int = 160) -> str:
    needle = (query or '').casefold().strip()
    candidates = []
    for source in (body, title):
        collapsed = re.sub(r'\s+', ' ', source or '').strip()
        if collapsed:
            candidates.append(collapsed)
    if not candidates:
        return ''
    chosen = candidates[0]
    pos = -1
    if needle:
        for collapsed in candidates:
            found = collapsed.casefold().find(needle)
            if found >= 0:
                chosen = collapsed
                pos = found
                break
        if pos < 0:
            for word in needle.split():
                for collapsed in candidates:
                    found = collapsed.casefold().find(word)
                    if found >= 0:
                        chosen = collapsed
                        pos = found
                        needle = word
                        break
                if pos >= 0:
                    break
    if pos < 0:
        frag = chosen[:limit]
    else:
        start = max(0, pos - 40)
        end = min(len(chosen), pos + max(len(needle), 1) + 80)
        frag = chosen[start:end]
        if start > 0:
            frag = '...' + frag
        if end < len(chosen):
            frag = frag + '...'
    if len(frag) > limit:
        frag = frag[:limit - 3].rstrip() + '...'
    return frag


def _fill_fts(conn, rows) -> None:
    try:
        conn.execute(
            '''
            CREATE VIRTUAL TABLE records_fts USING fts5(
                id UNINDEXED,
                type UNINDEXED,
                title,
                status UNINDEXED,
                created UNINDEXED,
                path UNINDEXED,
                body
            )
            '''
        )
    except sqlite3.OperationalError:
        return
    conn.executemany(
        'INSERT INTO records_fts (id, type, title, status, created, path, body) VALUES (?, ?, ?, ?, ?, ?, ?)',
        rows,
    )


def _fts_hits(conn, query) -> dict:
    tokens = re.findall(r'[A-Za-z0-9]+', query or '')
    if not tokens:
        return {}
    found = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow') AND name = 'records_fts'"
    ).fetchone()
    # fts5 virtual tables show up as type='table'.
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'records_fts'"
    ).fetchone()
    if not exists:
        return {}
    match = ' AND '.join('"%s"' % token for token in tokens[:12])
    try:
        hits = {}
        for ident, rank in conn.execute(
            'SELECT id, bm25(records_fts) FROM records_fts WHERE records_fts MATCH ?',
            (match,),
        ):
            hits[ident] = rank
        return hits
    except sqlite3.OperationalError:
        return {}
