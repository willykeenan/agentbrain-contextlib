# MCP server

ContextLib speaks MCP over stdio so Claude Code, Codex, Cursor, and other MCP clients can read and write the same project files a person opens in Finder.

```bash
ctxlib mcp --identity ID
```

The library path is `--library PATH`, else `CONTEXTLIB_ROOT`, else `~/ContextLib`. Example:

```bash
CONTEXTLIB_ROOT="/Volumes/SSD/ContextLib" ctxlib mcp --identity claude:lighthouse
```

## Protocol

Stdio JSON-RPC. Protocol versions:

- `2024-11-05`
- `2025-03-26`
- `2025-06-18`

The server negotiates one of those versions with the client. Tools are named `context_*`.

## Identity

`--identity ID` is fixed for the life of the process. Every write uses that identity as `author`. Tools have no parameter that can impersonate another writer.

Use an exact identity, the same shape records store:

- `mara`
- `codex:<thread>`
- `claude:<session>`
- `cursor:<session>`
- `service:<name>`

## Tools

| Tool | Role |
| --- | --- |
| `context_brief` | Always-loaded project summary (≤ 8192 bytes) |
| `context_search` | Ranked search over the rebuildable index |
| `context_get` | One record: meta, body, path, evidence state, supersession chain |
| `context_record` | Create a record (decision, requirement, fact, lesson, glossary, source, return, brief-note) |
| `context_supersede` | Supersede an old id with a new id; move the old file |
| `context_review_due` | Records whose `review_by` is due |
| `context_review` | `confirm` or `retire` a record |
| `context_capture` | `RESULT.json` → `return` record, proposed lessons to inbox |
| `context_export` | Zip a project (`include_private` defaults false) |
| `context_import` | Import a bundle |
| `context_status` | Library / project health: counts, inbox, due, index age |

Writes that the scanner flags as a secret or an absolute home path fail. Errors are returned as MCP `isError` results (the tool result, not a thrown JSON-RPC crash), with a plain-English message.

Inbox rules match the CLI: facts with evidence, records by owners/librarian, and records with `approved_by` become `current`; other writes land in `inbox/` as `proposed` until `accept`.

## Client setup

Replace the identity and the library path. `/Volumes/SSD/ContextLib` is the SSD layout described in [SSD.md](SSD.md).

### Claude Code

User or project MCP config (`mcpServers`):

```json
{
  "mcpServers": {
    "contextlib": {
      "command": "ctxlib",
      "args": ["mcp", "--identity", "claude:project"],
      "env": {
        "CONTEXTLIB_ROOT": "/Volumes/SSD/ContextLib"
      }
    }
  }
}
```

### Codex

```json
{
  "mcpServers": {
    "contextlib": {
      "command": "ctxlib",
      "args": ["mcp", "--identity", "codex:project"],
      "env": {
        "CONTEXTLIB_ROOT": "/Volumes/SSD/ContextLib"
      }
    }
  }
}
```

### Cursor

Project file `.cursor/mcp.json`, or user file `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "contextlib": {
      "command": "ctxlib",
      "args": ["mcp", "--identity", "cursor:project"],
      "env": {
        "CONTEXTLIB_ROOT": "/Volumes/SSD/ContextLib"
      }
    }
  }
}
```

After connecting, a typical first call is `context_brief` on the project slug, then `context_search` / `context_get` before `context_record`.

## What the server will not do

It will not switch identity mid-session. It will not put secrets or absolute home paths into a record. It will not treat `index.sqlite` as source of truth: `context_search` reads the index, and `rebuild` (CLI) recreates that index from the Markdown files.
