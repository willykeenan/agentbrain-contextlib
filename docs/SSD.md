# Keeping the library on an SSD

ContextLib is a folder of Markdown files. The folder can live on an external SSD, ride in a bag, and still make sense in Finder with the network off.

A typical root is `/Volumes/SSD/ContextLib` or `/Volumes/SSD/ContextLib`. Set it once:

```bash
export CONTEXTLIB_ROOT="/Volumes/SSD/ContextLib"
ctxlib init "$CONTEXTLIB_ROOT" --project lighthouse-app --name "Lighthouse App"
```

`library.json` at that root identifies the library (`format: contextlib/1`, a `library_id`, `created`). Copying the folder copies the identity.

## Finder reading order

You do not need the CLI to learn a project. In Finder:

1. **Library `README.md`** — what this folder is, and how to read it in ten minutes.
2. **Library `INDEX.md`** — one line per project (purpose, last change, brief date).
3. **`projects/<slug>/README.md`** — purpose, plus links to BRIEF, INDEX files, and GLOSSARY.
4. **`projects/<slug>/BRIEF.md`** — the always-loaded summary (≤ 8192 bytes).
5. **`projects/<slug>/decisions/INDEX.md`** — current decisions first, superseded below, newest first.

From there, open a single decision file, or skip to `requirements/INDEX.md`, `facts/INDEX.md`, `GLOSSARY.md`, `TIMELINE.md`. Each type folder uses the same INDEX shape: **Current**, then **Superseded**.

That path is the contract. Agents load `BRIEF.md` first for the same reason a person does: it fits in one sitting.

## Unplugged use

Work proceeds from files on disk. A local clone of the library is enough.

On the machine that will leave the desk:

```bash
# one-time: copy the SSD library to the internal disk
cp -R "/Volumes/SSD/ContextLib" ~/ContextLib-offline
export CONTEXTLIB_ROOT=~/ContextLib-offline
```

Add records, accept inbox items, regenerate BRIEF and INDEX files:

```bash
ctxlib add lighthouse-app fact "Fog horn tested" --body "**Fact:** …" --author mara
ctxlib regen lighthouse-app
ctxlib brief lighthouse-app
```

When the SSD (or the network, if the library is also a git repo) is back:

```bash
ctxlib sync
```

`sync` runs `git pull` / `git push` when the library is a git repository. When it is not, `sync` is a no-op with a message; copy the folder back to the SSD yourself. The `git` binary is optional for every other command.

Keepers, harbor masters, and agents all write the same Markdown. There is no pending queue that exists only inside a running model.

## Moving between Macs

The portable unit is the library folder. `library.json` is the identity; the Markdown is the data; `.contextlib/index.sqlite` is disposable.

On the destination Mac:

1. Copy the folder (SSD, AirDrop, `git clone`).
2. Point `CONTEXTLIB_ROOT` (or `--library`) at it.
3. Rebuild the search index: `ctxlib rebuild`.
4. Confirm Finder still reads: library README → project BRIEF → `decisions/INDEX.md`.
5. Run `ctxlib doctor --ten-minute` on a project.

You do not re-mint `library_id`. You do not export-import unless you want a zip snapshot. A new Mac with the same files is the same library.

`.contextlib/ledger/<writer-slug>.jsonl` is a hash-chained write log per writer. Bring it along with the files. `index.sqlite` can be missing; `rebuild` recreates it.

## Why the database is only an index

`.contextlib/index.sqlite` exists so `ctxlib search` and `context_search` are fast. It is git-ignored because it is a cache.

- Every record is a Markdown file whose `body_sha256` covers the body after the closing `---`.
- `rebuild` walks those files and fills SQLite. If the file and the row disagree, the file wins — you rebuild.
- Export / import round-trips hashes of records, not rows in SQLite.
- Finder, `git diff`, an editor on another OS, and the MCP server all see the same bytes.

If the SSD is unplugged and `index.sqlite` is stale or absent, the library is still complete. Open BRIEF. Open `decisions/INDEX.md`. That is the source of truth.
