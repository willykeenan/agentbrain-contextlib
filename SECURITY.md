# Security Policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository. Include the ContextLib version (`ctxlib` / `agentbrain-contextlib` 0.1.x), the command or MCP tool involved, and a minimal record or file that shows the problem.

Do not attach live secrets. Redact tokens and paste a shape that the scanner should have caught.

## What the library already guards

Writes go through a scanner (`scan_text`). A record is refused when the scanner finds:

- a **secret** (typical token and private-key shapes)
- an **absolute home path**

Evidence refs cannot be absolute paths. Allowed prefixes: `project:`, `ssd:`, `room:`, `url:` (https only), `note:`.

Records marked `sensitivity: private` stay on the machine in the default export. `ctxlib export` includes them only with `--include-private`. MCP `context_export` follows the same default.

The SQLite file under `.contextlib/index.sqlite` is a search index rebuilt from Markdown. Treat the files as the trust boundary; rebuilding the index does not grant new access to private records.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## Scope

ContextLib runs locally against a folder you point it at (`--library`, `CONTEXTLIB_ROOT`, or `~/ContextLib`). The MCP server binds the writer identity at process start and has no tool for switching identity.
