---
id: req-20260912-e5f6
type: requirement
title: Show live lamp character on the harbor board
status: current
project: lighthouse-app
scope: {lane: harbor-board, team: harbor-master}
created: 2026-09-12T10:15:00Z
author: mara
evidence:
  - {ref: "project:decisions/2026-09-12_use-keeper-logs-as-the-lamp-status-source-of-truth_a1b2.md"}
  - {ref: "note:harbor master wall glance in under two seconds"}
supersedes: []
superseded_by: null
review_by: null
tags: [lamp, board, character]
sensitivity: normal
body_sha256: "9fe726fcc9a05e428d8a37ba1f0c15f8aa0460b8b71cbe4912e924b88fa704dd"
---
**Requirement:** The harbor board shows the current lamp character (for example Fl W 15s), the time it was signed, and whether it is stale.

**Why:** A harbor master glancing at the wall must know what the light is doing without opening the log.

**Acceptance:** A signed log line appears on the board. A log older than 15 minutes shows a stale badge. The character string matches the glossary term.
