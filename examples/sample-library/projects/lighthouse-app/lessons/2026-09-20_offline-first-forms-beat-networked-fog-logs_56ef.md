---
id: les-20260920-56ef
type: lesson
title: Offline-first forms beat networked fog logs
status: current
project: lighthouse-app
scope: {lane: fog-signal, team: keepers}
created: 2026-09-20T21:10:00Z
author: mara
evidence:
  - {ref: "project:returns/2026-09-20_keeper-trial-20-sep-2026_e5f7.md"}
  - {ref: "note:three fog events in the paper book, missing from the WAN log"}
supersedes: []
superseded_by: null
review_by: 2027-09-20
tags: [fog, offline, forms]
sensitivity: normal
body_sha256: "d8ddd1d4d3bc81ffb4d2c01cdc6b277a6f44f4be76e7c6ed3e834451abdc6dbf"
---
**Lesson:** Fog-log forms that require a network round-trip get skipped. Offline-first forms get filled.

**Context:** During the 20 Sep keeper trial, three fog events were missing from the server log and present in the paper book.

**What to do:** Write records to local files; sync when the link is back. Never block a keeper on HTTP.
