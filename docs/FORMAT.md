# ContextLib record format

ContextLib stores each piece of project knowledge as one UTF-8 Markdown file. The files are the source of truth. `projects/<slug>/.contextlib/index.sqlite` is a search index rebuilt from those files. This document is the format those files use, and the rules the core library enforces.

The grammar is a small YAML-like subset, parsed by ContextLib. It is not a general YAML parser.

## File shape

A record starts with a front-matter block and a Markdown body. The newline after the closing `---` is the separator. It is not part of the body. The body is every byte after that newline, including a trailing newline when the file has one.

```
---
id: dec-20260926-7f3a
type: decision
title: "Use plain files as the source of truth"
status: current
project: lighthouse-app
scope: {lane: workstream, team: owner}
created: "2026-09-26T14:03:00Z"
author: mara
approved_by: "mara — \"files first, database is only an index\""
evidence:
  - {ref: "project:BRIEF.md"}
  - {ref: "url:https://example.com/x"}
supersedes: []
superseded_by: null
review_by: 2027-03-25
tags: [storage, library]
sensitivity: normal
body_sha256: "<64 lowercase hex digits>"
---
**Decision:** Keep the Markdown files as the source of truth.
```

`body_sha256` is the SHA-256 hex digest of the UTF-8 body. It is not a hash of the whole file.

## Front matter

Supported values:

- scalars: bare tokens, double-quoted strings, single-quoted strings, `null`, `true`, `false`
- inline lists of scalars: `[storage, library]` or `[]`
- inline flat maps: `{lane: harbor-board, team: keepers}`
- block lists of flat maps, which is how evidence is written:

```
evidence:
  - {ref: "note:keeper log 2026-09-12"}
  - {ref: "url:https://www.iala.int/", sha256: "<64 hex>"}
```

A `#` comment starts at a `#` that is outside a string and is preceded by whitespace or the start of the line. Nested maps are rejected. Indented lines are only legal as block-list items.

The canonical renderer (`render_record`) emits keys in this order:

`id`, `type`, `title`, `status`, `project`, `scope`, `created`, `author`, `approved_by`, `evidence`, `supersedes`, `superseded_by`, `review_by`, `tags`, `sensitivity`, `body_sha256`.

`scope` and `approved_by` are omitted when absent. `superseded_by` and `review_by` are written as `null` when empty. `evidence`, `supersedes`, and `tags` are written even when empty. Scalars that are not a single plain token (letters, digits, `.`, `_`, `+`, `/`, `-`) are double-quoted. `body_sha256` is always quoted. Parsing accepts both quoted and bare forms, which is how the hand-written sample library stays valid.

## Types, ids, filenames

| Type | Prefix | Folder |
| --- | --- | --- |
| `decision` | `dec` | `decisions/` |
| `requirement` | `req` | `requirements/` |
| `fact` | `fact` | `facts/` |
| `lesson` | `les` | `lessons/` |
| `glossary` | `glo` | `glossary/` |
| `source` | `src` | `sources/` |
| `return` | `ret` | `returns/` |
| `brief-note` | `note` | `notes/` |

An id is `<prefix>-<YYYYMMDD>-<4 lowercase hex>`. The date matches `created`. A filename is `<YYYY-MM-DD>_<title-slug>_<id-suffix>.md`. The title slug is lowercase, with non-alphanumeric runs turned into single hyphens.

`status` is `proposed`, `current`, `superseded`, or `retired`.

| Status | Where the file lives |
| --- | --- |
| `proposed` | `inbox/` |
| `current` | the type folder |
| `superseded` | `<type>/superseded/` |
| `retired` | the type folder, or `inbox/rejected/` when it was rejected from the inbox |

Default `review_by`, counted in days after `created` (overridable in `project.json` `review_defaults`):

| Type | Days |
| --- | --- |
| fact | 30 |
| source | 90 |
| decision | 180 |
| lesson | 365 |
| glossary | 365 |
| brief-note | 30 |
| requirement | null (open until closed) |
| return | null |

## Evidence

A ref is one of:

- `project:<relative path>` under the project directory
- `ssd:<relative path>` under the library root, or the project directory if that is where the file is
- `room:<name>#<seq>`
- `url:https://...` (https only)
- `note:<text>`

Absolute paths, `..`, and non-https URLs are invalid. An optional `sha256` pins file bytes for `project:` and `ssd:` refs. `get` reports each ref as `ok` (pin matches), `changed` (pin differs), `missing` (file ref with no file), or `unchecked` (no pin, or a ref that is not a local file).

## Who becomes current

`record` chooses `status` when the caller does not pass one:

- a **fact with evidence** is `current`
- a record whose **author is a project owner or a librarian** (`librarian`, `librarian:…`, or `service:librarian`) is `current`
- a record with **`approved_by`** set is `current`
- everything else is `proposed` and is written under `inbox/`

`accept` moves a proposed file into its type folder and sets `status: current`. `reject` moves it to `inbox/rejected/` and sets `status: retired`. Passing `status=` explicitly overrides the default.

`request_key` makes `record` idempotent. The key is stored on the ledger line, not in the Markdown. A second call with the same key returns the original `{id, path, status}` and does not write another file.

## Append-only

The body is never edited. `body_sha256` stays the digest of that same body.

The one content change allowed on an existing file is a front-matter patch of status fields:

- **supersede** sets `status: superseded` and `superseded_by` to the new id, then moves the file to `<type>/superseded/`. The body bytes and `body_sha256` line are unchanged.
- **accept** sets `status: current` and moves the file out of `inbox/`.
- **reject** and **retire** set `status: retired`.
- **confirm** may set `review_by` to the next review date.

`supersede(project, old_id, new_id, reason, author=...)` does not create the new record. Create it first with `record(..., supersedes=(old_id,))`, then call `supersede`. The reason is stored on the ledger line.

## Ledger

Every write appends one JSON line to `projects/<slug>/.contextlib/ledger/<writer-slug>.jsonl`. The writer slug is the library writer lowercased, with non-alphanumeric runs turned into hyphens. The chain is per writer file.

Each line is a JSON object with:

| Field | Meaning |
| --- | --- |
| `seq` | 1-based integer, per file |
| `at` | UTC timestamp `YYYY-MM-DDThh:mm:ssZ` |
| `writer` | the library writer identity |
| `action` | `record`, `supersede`, `review`, `accept`, `reject`, or `import` |
| `id` | record id |
| `path` | path relative to the project directory |
| `sha256` | SHA-256 of the record file bytes after that write |
| `prev_hash` | previous line's `hash`, or `null` on the first line |
| `hash` | chain hash, defined below |

Optional fields, included only when present: `author`, `request_key`, `reason`, `outcome`, `note`.

`hash` is the SHA-256 of the UTF-8 JSON object containing the core fields plus any optional fields that are present. JSON is serialized with sorted keys, separators `,` and `:`, and non-ASCII characters left as themselves. The `hash` field is not part of the payload it names.

## Sensitivity, index, brief, capture

`sensitivity` is `normal` or `private`. `export` skips private records unless `include_private` is true. Import writes the original record bytes. A record whose id is already present with a different `body_sha256` is reported in `conflicts` and is not overwritten.

`Index.rebuild` deletes the project's index rows and inserts one row per record file. `search` reads that index. Until `rebuild`, search does not see new files. Full-text search is used when SQLite has FTS5; otherwise ranking is a case-insensitive substring score (title matches outrank body matches).

`build_brief` returns the always-loaded summary: purpose, current decisions (title and one line), open requirements, key facts, recent returns, the review-due count, and the generated time. The UTF-8 text is at most 8192 bytes, including when the project has hundreds of records. `regenerate` writes that text to `BRIEF.md` and rewrites `GLOSSARY.md`, `TIMELINE.md`, every `INDEX.md`, the project `README.md`, and the library `INDEX.md`.

`capture_result` reads `RESULT.json`. When `userOutcome`, `remainingGaps`, or `nextActor` is present, those fields become the return body; otherwise the body is `summary`. Evidence pins the file's SHA-256. Lessons under `lessons` are written as `proposed` inbox records. The return itself is `current`.

Writes are refused when `scan_text` finds a secret or an absolute home-directory path. Secrets include vendor token shapes, private-key blocks, and assignments that look like an API key or a password. Home-directory paths are the usual per-user prefixes on macOS, Linux, and Windows, including a tilde slash. The scanner returns `{kind, line, hint}` and never returns the matched characters. `kind` is `secret` or `abs-path`.

## Git

Core reads and writes do not invoke `git`. A library that is not a git repository, and a machine with no `git` binary, can still init, record, supersede, export, import, regenerate, and rebuild the index.
