# Sample ContextLib library

This folder is a ContextLib library (`format: contextlib/1`). Everything that matters is a Markdown file. The SQLite file under `.contextlib/` is a search index rebuilt from these files.

The invented project is **lighthouse-app**: a harbor dashboard that coordinates lamp status, fog signals, and vessel traffic for a fictional headland light.

## How to read this in 10 minutes (Finder)

1. This page — you are here.
2. [`INDEX.md`](INDEX.md) — one line per project.
3. [`projects/lighthouse-app/README.md`](projects/lighthouse-app/README.md) — purpose and links.
4. [`projects/lighthouse-app/BRIEF.md`](projects/lighthouse-app/BRIEF.md) — the always-loaded summary (≤ 8192 bytes).
5. [`projects/lighthouse-app/decisions/INDEX.md`](projects/lighthouse-app/decisions/INDEX.md) — current decisions, then superseded, newest first.

That is the same order to use on an external SSD. See `docs/SSD.md` in the ContextLib repository.

## From the CLI

```bash
ctxlib --library examples/sample-library brief lighthouse-app
ctxlib --library examples/sample-library doctor lighthouse-app --ten-minute
```

Agents use the same files through `ctxlib mcp --identity ID`.
