# ContextLib: build spec (v0.1)

**ContextLib** is a project library that outlives every agent session. Each project's knowledge (decisions, requirements, facts, lessons, glossary, sources and returned work) is stored as plain Markdown files with front-matter in one folder per project. The folders can sit on an external SSD, and a person can understand a project from Finder alone. Agents read and write the same files through a CLI (`ctxlib`) and an MCP server (`context_*` tools). Any database is a search index rebuilt from the files, never the source of truth.

It is the open core of the context plugin of AgentBrain (agentrooms.io).

**Naming rules:** the Python package is `agentbrain_contextlib` and the CLI is `ctxlib`. Never name a module `contextlib`, because that shadows the standard library.

**Constraints:**
- Python 3.9+, **standard library only**. The optional `git` binary is used via subprocess when present; everything works without git.
- License: Apache-2.0, copyright "KE Studios".
- No private data anywhere: no absolute home paths, no emails, no tokens.

## Library layout

```
<library root>/                        e.g. "/Volumes/SSD/ContextLib" or "/Volumes/SSD/ContextLib"
├── README.md                          generated: what this is, how to read it in 10 minutes
├── INDEX.md                           generated: one line per project (purpose, last change, brief date)
├── library.json                       {"format": "contextlib/1", "library_id": "<uuid4>", "created": ISO}
└── projects/<project-slug>/           one folder (and optionally one git repo) per project
    ├── README.md                      generated start-here page: purpose, links to BRIEF, INDEX files, GLOSSARY
    ├── project.json                   {"slug","name","purpose","created","owners":[identity],"review_defaults":{type: days}}
    ├── BRIEF.md                       generated, ≤ 8192 bytes, the always-loaded summary
    ├── GLOSSARY.md  TIMELINE.md       generated
    ├── decisions/ requirements/ facts/ lessons/ glossary/ sources/ returns/
    │   ├── INDEX.md                   generated: "Current" then "Superseded", newest first
    │   ├── <YYYY-MM-DD>_<title-slug>_<id-suffix>.md
    │   └── superseded/                superseded records moved here unchanged (body hash still valid)
    ├── inbox/                         proposed records awaiting review; inbox/rejected/ for rejected ones
    ├── exports/
    └── .contextlib/                   hidden: ledger/<writer-slug>.jsonl (hash-chained), index.sqlite (rebuildable, git-ignored)
```

## Record file format

A record is a UTF-8 Markdown file. It starts with a YAML-like front-matter block (a restricted subset, parsed by our own small parser: scalars, quoted strings, lists of scalars, lists of flat maps). The body is plain Markdown.

```
---
id: dec-20260926-7f3a
type: decision
title: Use plain files as the source of truth
status: current                 # proposed | current | superseded | retired
project: pid-migration
scope: {lane: workstream, team: owner}
created: 2026-09-26T14:03:00Z
author: codex:<thread>          # exact identity: codex:<thread>, claude:<session>, mara, service:<name>
approved_by: mara — "files first, database is only an index"   # optional, verbatim quote
evidence:
  - {ref: "project:OWNER-BRIEF.md", sha256: "..."}
  - {ref: "url:https://example.com/x"}
supersedes: []
superseded_by: null
review_by: 2027-03-25
tags: [storage, library]
sensitivity: normal             # normal | private (private never leaves the machine in exports by default)
body_sha256: "..."              # sha256 of the body text after the closing ---
---
**Decision:** …
**Why:** …
**Consequences:** …
**How to verify:** …
```

- **Types:** `decision`, `requirement`, `fact`, `lesson`, `glossary`, `source`, `return`, `brief-note`.
- **Default `review_by` (days after creation):** fact 30, source 90, decision 180, lesson 365, glossary 365, requirement null (open until closed), return null, brief-note 30. These can be overridden in project.json.
- **ids:** `<type prefix>-<YYYYMMDD>-<4 hex>`. Prefixes: dec, req, fact, les, glo, src, ret, note.
- **evidence refs:** only `project:<relative path>`, `ssd:<relative path>`, `room:<name>#<seq>`, `url:<https url>` or `note:<text>`. No absolute paths.
- **Append-only:** a record's body and front-matter are never rewritten, with one exception. Superseding sets `status: superseded` and `superseded_by`, and moves the file to `superseded/`. Every write also appends a ledger line `{seq, at, writer, action, id, path, sha256, prev_hash, hash}`, hash-chained per writer file.

## Core API (`src/agentbrain_contextlib/`) — the contract between parts

```python
# records.py
TYPES = ('decision','requirement','fact','lesson','glossary','source','return','brief-note')
STATUSES = ('proposed','current','superseded','retired')
def parse_record(text: str) -> dict                  # {'meta': {...}, 'body': str}; raises ValueError on bad format
def render_record(meta: dict, body: str) -> str      # canonical text (stable key order); computes body_sha256
def new_id(type_: str, when=None) -> str
def validate(meta: dict, body: str) -> list[str]     # list of problems (empty = valid)

# scanner.py
def scan_text(text: str) -> list[dict]               # [{'kind': 'secret'|'abs-path', 'line': n, 'hint': str}]; values never returned

# library.py
class Library:
    def __init__(self, root, clock=None, writer='cli'): ...
    @classmethod
    def init(cls, root) -> 'Library'                 # creates README/INDEX/library.json if missing
    def projects(self) -> list[dict]
    def create_project(self, slug, name, purpose='', owners=()) -> dict
    def record(self, project, type_, title, body, *, author, evidence=(), supersedes=(), review_by=None,
               scope=None, tags=(), sensitivity='normal', approved_by=None, status=None, request_key=None) -> dict
        # returns {'id','path','status'}; status defaults: facts with evidence and records by owners/librarian/with approved_by -> current, else proposed (inbox/)
        # refuses (ValueError) when scan_text finds a secret or absolute home path; idempotent on request_key
    def get(self, project, id_) -> dict              # {'meta','body','path','supersession_chain':[ids],'evidence':[{ref,sha256,state:'ok'|'changed'|'missing'|'unchecked'}]}
    def supersede(self, project, old_id, new_id, reason, *, author) -> dict
    def review(self, project, id_, outcome, note, *, author, next_review_by=None) -> dict   # confirm|retire|supersede(requires new_id in note? no: use supersede())
    def accept(self, project, id_, *, author) -> dict   # inbox -> current
    def reject(self, project, id_, reason, *, author) -> dict
    def review_due(self, project, before=None) -> list[dict]
    def list(self, project, type_=None, status='current') -> list[dict]
    def regenerate(self, project) -> dict            # rewrites BRIEF.md (≤8192 bytes), GLOSSARY.md, TIMELINE.md, every INDEX.md, README.md, root INDEX.md; returns sizes
    def export(self, project, out_dir, include_private=False) -> dict   # zip; returns {'path','sha256','records'}
    def import_bundle(self, bundle_path) -> dict     # {'project','records','conflicts'}

# index.py
class Index:                                         # .contextlib/index.sqlite, rebuildable
    def __init__(self, library): ...
    def rebuild(self, project=None) -> int
    def search(self, project, query, type_=None, status='current', limit=20) -> list[dict]  # {id,type,title,status,date,path,snippet}; simple ranked LIKE/FTS if available

# brief.py
def build_brief(library, project) -> str             # ≤ 8192 bytes: purpose, current decisions (titles + one line), open requirements, key facts, recent returns, review-due count, generated time

# capture.py
def capture_result(library, project, result_path, *, author='service:capture') -> dict
    # RESULT.json -> a 'return' record (userOutcome/remainingGaps/nextActor fields when present; otherwise summary),
    # evidence pinned to the file sha256; proposes lessons listed under "lessons" to inbox; returns {'return_id','proposed_ids'}
```

## Parts (each part writes only its own files)

### A. Core
- **Files:** `records.py`, `scanner.py`, `library.py`, `index.py`, `brief.py`, `capture.py`, `__init__.py`, `docs/FORMAT.md`, `schema/record.schema.json`, `tests/test_records.py`, `tests/test_library.py`, `tests/test_index.py`, `tests/test_brief.py`, `tests/test_capture.py`, `tests/test_scanner.py`.
- **Tests must prove:**
  - The format round-trips.
  - Append-only: bodies are never rewritten, and supersede moves the file and keeps the body hash valid.
  - The ledger hash chain.
  - Secret/abs-path refusal.
  - Inbox vs current rules.
  - Idempotent `request_key`.
  - The brief stays ≤ 8192 bytes even with 500 records.
  - The index rebuild matches files only.
  - Export/import round trip keeps every hash.
  - Git is optional.

### B. CLI + MCP + doctor + importers
- **Files:** `cli.py`, `__main__.py`, `mcp.py`, `doctor.py`, `importers.py`, `tests/test_cli.py`, `tests/test_mcp.py`, `tests/test_doctor.py`, `tests/test_importers.py`.
- **CLI `ctxlib [--library PATH]`:**
  - The library path comes from `--library`, else env `CONTEXTLIB_ROOT`, else `~/ContextLib`.
  - Commands:
    - `init PATH [--project SLUG --name NAME --purpose TEXT]`
    - `project add SLUG NAME [--purpose]`, `project list`
    - `add PROJECT TYPE TITLE (--body TEXT | --body-file F) --author ID [--evidence REF ...] [--tag T ...] [--review-by DATE] [--approved-by TEXT]`
    - `get PROJECT ID`
    - `search PROJECT QUERY [--type] [--all]`
    - `brief PROJECT`
    - `supersede PROJECT OLD NEW --reason TEXT --author ID`
    - `review PROJECT ID confirm|retire --note TEXT --author ID`
    - `inbox PROJECT`, `accept PROJECT ID --author`, `reject PROJECT ID --reason --author`
    - `due PROJECT`
    - `regen PROJECT|--all`
    - `rebuild`
    - `capture PROJECT RESULT.json`
    - `import-md PROJECT FILE --type TYPE --author ID`
    - `export PROJECT OUT_DIR [--include-private]`, `import BUNDLE`
    - `doctor [PROJECT] [--ten-minute]`
    - `sync` (git pull/push when the library is a git repo; a no-op otherwise, with a message)
    - `mcp --identity ID`
- **MCP:** a stdio JSON-RPC server, protocol versions 2024-11-05, 2025-03-26 and 2025-06-18. It exposes the `context_*` tools: brief, search, get, record, supersede, review_due, review, capture, export, import, status.
  - The identity is fixed at start; tools can never write as another identity.
  - Errors come back as `isError` results.
- **Doctor:**
  - `--ten-minute` fails if:
    - README, BRIEF or INDEX is missing;
    - BRIEF is over 8192 bytes or more than 30 days old;
    - a current record has no evidence or no `review_by` (where required);
    - an absolute home path or secret is found;
    - the index does not rebuild;
    - the export/import round trip changes a hash.
  - It prints plain-English lines.
- **Importers:** Markdown file → record, and RESULT.json → return (via `capture`).

### C. Docs, packaging and demo
- **Files:** `README.md`, `pyproject.toml` (console script `ctxlib=agentbrain_contextlib.cli:main`), `docs/QUICKSTART.md`, `docs/MCP.md`, `docs/SSD.md`, `examples/sample-library/` (an invented project "lighthouse-app" with about 12 records covering every type, generated BRIEF and INDEX files), `space/` (a static Hugging Face Space: `index.html` that renders the sample library read-only in the browser from a bundled JSON, plus a README with front matter `sdk: static`), `.github/workflows/ci.yml` (py3.9–3.13, ubuntu+macos), `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `tests/test_packaging.py`.
- **docs/SSD.md** explains how to keep the library on an external SSD. It covers:
  - Finder reading order: README → BRIEF → `decisions/INDEX.md`.
  - Unplugged use: a local clone plus `ctxlib sync`.
  - Moving to another Mac via `library.json`.
  - Why the database is only an index.
- **README:** the front door. An honest pitch, why, a 60-second quickstart, MCP setup for Claude Code / Codex / Cursor, the format, and a closing line: "ContextLib is the open library layer of AgentBrain (agentrooms.io)."

## Definition of done
- `PYTHONPATH=src python3 -m unittest discover -s tests` passes on Python 3.9.
- `python3 tools/check.py package` passes (fresh venv install and CLI smoke).
- `ctxlib doctor --ten-minute` passes on `examples/sample-library`.
- No private data in the repo.
