# Changelog

All notable changes to ContextLib are documented here.

## 0.1.0 — 2026-09-26

First public release of the open library layer of AgentBrain.

- Plain-file project library, format `contextlib/1`: Markdown records with YAML-like front-matter, one folder per project.
- CLI `ctxlib` (`agentbrain_contextlib.cli:main`) for init, project, add, get, search, brief, supersede, review, inbox, due, regen, rebuild, capture, import-md, export, import, doctor, sync, mcp.
- MCP stdio server (`ctxlib mcp --identity ID`) with `context_*` tools; protocol versions 2024-11-05, 2025-03-26, 2025-06-18.
- Rebuildable SQLite search index; files remain the source of truth.
- Sample library `examples/sample-library/` with invented project `lighthouse-app`.
- Docs: quickstart, MCP client setup, SSD / Finder / unplugged use.
