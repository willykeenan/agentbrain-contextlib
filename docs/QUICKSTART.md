# Quickstart

Install the CLI, create a library, write a decision, and read it back the way Finder and an agent both will.

## Install

Python 3.9 or newer. No third-party runtime dependencies.

```bash
pip install "git+https://github.com/willykeenan/agentbrain-contextlib"
ctxlib --help
```

From a clone of this repository:

```bash
pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests
```

The console script is `ctxlib` → `agentbrain_contextlib.cli:main`.

## Create a library

```bash
ctxlib init ~/ContextLib --project lighthouse-app \
  --name "Lighthouse App" \
  --purpose "Harbor dashboard for lamp status, fog signals, and traffic"
```

`init` writes `README.md`, `INDEX.md`, and `library.json` at the library root, then the project folder (`project.json`, `README.md`, type directories).

Point later commands at the same tree with `--library PATH` or:

```bash
export CONTEXTLIB_ROOT=~/ContextLib
```

If both are unset, `ctxlib` uses `~/ContextLib`.

## Write and read records

```bash
ctxlib add lighthouse-app decision "Use keeper logs as lamp status" \
  --body "**Decision:** Lamp status comes from keeper logs, not AIS." \
  --author mara \
  --evidence "note:keeper log 2026-09-12" \
  --tag lamp --tag keeper-log \
  --approved-by 'mara — "files first, the light is what the keeper signed"'

ctxlib add lighthouse-app fact "Lamp character is Fl W 15s" \
  --body-file ./character.md \
  --author mara \
  --evidence "url:https://www.iala.int/"

ctxlib brief lighthouse-app
ctxlib get lighthouse-app dec-20260912-a1b2
ctxlib search lighthouse-app "lamp character" --type fact
```

`add` types: `decision`, `requirement`, `fact`, `lesson`, `glossary`, `source`, `return`, `brief-note`.

Status defaults: a fact with evidence, a record by an owner or librarian, or a record with `--approved-by` lands as `current`. Everything else lands as `proposed` in `inbox/`.

```bash
ctxlib inbox lighthouse-app
ctxlib accept lighthouse-app req-20260913-789a --author mara
ctxlib reject lighthouse-app note-20260921-a7b8 --reason "folded into BRIEF" --author mara
```

Supersede instead of editing a body. The old file moves to `superseded/`; its `body_sha256` stays valid.

```bash
ctxlib supersede lighthouse-app dec-20260905-c0de dec-20260912-a1b2 \
  --reason "AIS is traffic, not lamp status" \
  --author mara
```

## Brief, due list, doctor

```bash
ctxlib brief lighthouse-app
ctxlib due lighthouse-app
ctxlib regen lighthouse-app
ctxlib rebuild
ctxlib doctor lighthouse-app --ten-minute
```

`brief` prints the always-loaded summary (purpose, current decisions, open requirements, key facts, recent returns, review-due count). It stays ≤ 8192 bytes.

`doctor --ten-minute` fails if README / BRIEF / INDEX is missing, BRIEF is over 8192 bytes or more than 30 days old, a current record is missing evidence or a required `review_by`, an absolute home path or secret is found, the index does not rebuild, or an export/import round trip changes a hash.

## Capture a result, export a zip

```bash
ctxlib capture lighthouse-app ./RESULT.json
ctxlib export lighthouse-app ./exports
ctxlib import ./exports/lighthouse-app.zip
ctxlib import-md lighthouse-app ./notes/fog.md --type lesson --author mara
```

`capture` writes a `return` record. Lessons listed in the result are proposed into `inbox/`.

## MCP

```bash
ctxlib mcp --identity mara
```

Stdio JSON-RPC. Wire it into Claude Code, Codex, or Cursor as in [MCP.md](MCP.md). The identity is process-wide; tools cannot write as someone else.

## Open the sample in Finder

This repository already contains a hand-written library at [`examples/sample-library/`](../examples/sample-library/).

1. Open `examples/sample-library/README.md`.
2. Open `projects/lighthouse-app/BRIEF.md`.
3. Open `projects/lighthouse-app/decisions/INDEX.md`.

That is the same reading order you use on an SSD. See [SSD.md](SSD.md) for unplugged use and moving the folder between Macs.

```bash
ctxlib --library examples/sample-library brief lighthouse-app
ctxlib --library examples/sample-library doctor lighthouse-app --ten-minute
```

## Sync (git is optional)

If the library folder is a git repo, `ctxlib sync` pulls and pushes. If it is not, `sync` prints that it is a no-op and exits successfully. Everything else works without the `git` binary.
