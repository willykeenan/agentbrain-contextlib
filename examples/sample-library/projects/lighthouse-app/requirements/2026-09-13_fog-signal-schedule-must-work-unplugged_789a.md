---
id: req-20260913-789a
type: requirement
title: Fog-signal schedule must work unplugged
status: current
project: lighthouse-app
scope: {lane: fog-signal, team: keepers}
created: 2026-09-13T08:40:00Z
author: mara
evidence:
  - {ref: "note:hut Wi-Fi drops in fog"}
  - {ref: "ssd:exports/keeper-trial.zip"}
  - {ref: "room:harbor#4"}
supersedes: []
superseded_by: null
review_by: null
tags: [fog, offline, ssd]
sensitivity: normal
body_sha256: "07bd91d04a7fdf28b5227669657a06f76816591fd687918f8fc596366c8e6c26"
---
**Requirement:** The fog-signal schedule can be read and updated with the SSD unplugged and with no network.

**Why:** Fog does not wait for a WAN. Keepers already work from the hut with a local clone of the library.

**Acceptance:** `ctxlib brief lighthouse-app` and the fog panel both load from local files. An update written offline syncs later with `ctxlib sync`.
