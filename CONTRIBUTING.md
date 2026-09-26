# Contributing

ContextLib is the open library layer of AgentBrain. The runtime is Python 3.9+ and the **standard library only**. The optional `git` binary is called through subprocess when present; every command still works without it.

Never name a module `contextlib` — that shadows the standard library. The package is `agentbrain_contextlib`. The CLI is `ctxlib`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests
python3 tools/check.py packaging
```

## Layout

| Path | What belongs there |
| --- | --- |
| `src/agentbrain_contextlib/` | Library code (`records`, `scanner`, `library`, `index`, `brief`, `capture`, CLI, MCP) |
| `docs/` | SPEC, FORMAT, QUICKSTART, MCP, SSD |
| `examples/sample-library/` | Finder-readable demo (`lighthouse-app`) |
| `tests/` | `unittest` modules, standard library only |
| `schema/` | JSON Schema for a record |

Do not add runtime third-party dependencies. Tests that cover packaging parse sample records with the standard library and do not import the package.

## Records

The files on disk are the source of truth.

- Append-only: do not rewrite a record body. Supersede, then move the old file to `superseded/`.
- Evidence refs are `project:`, `ssd:`, `room:`, `url:` (https), or `note:`. No absolute paths.
- The scanner must refuse secrets and absolute home paths.
- `body_sha256` is the SHA-256 of the body text after the closing `---`.
- Ids: `<prefix>-<YYYYMMDD>-<4 hex>`. Prefixes: `dec`, `req`, `fact`, `les`, `glo`, `src`, `ret`, `note`.
- Generated pages (`BRIEF.md` ≤ 8192 bytes, `INDEX.md`, `GLOSSARY.md`, `TIMELINE.md`, README files) are rewritten by `ctxlib regen`.

## Pull requests

- Keep the change in the part you are touching (core, CLI/MCP, or docs/packaging).
- Include tests that fail without the change.
- Run `PYTHONPATH=src python3 -m unittest discover -s tests` on Python 3.9.
- No private data in the tree: no absolute home paths, no emails, no tokens.

Apache-2.0, copyright KE Studios.
