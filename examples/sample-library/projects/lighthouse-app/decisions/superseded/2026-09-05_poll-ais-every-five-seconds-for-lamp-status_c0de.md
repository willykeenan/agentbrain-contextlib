---
id: dec-20260905-c0de
type: decision
title: Poll AIS every five seconds for lamp status
status: superseded
project: lighthouse-app
scope: {lane: harbor-board, team: keepers}
created: 2026-09-05T16:20:00Z
author: "codex:lighthouse-1"
evidence:
  - {ref: "note:early prototype treated AtoN reports as the lamp"}
  - {ref: "url:https://www.iala.int/"}
supersedes: []
superseded_by: dec-20260912-a1b2
review_by: 2027-03-04
tags: [lamp, ais]
sensitivity: normal
body_sha256: "389bcf3c92bdf74fcb0cb5c25d5b0d78d76418263daa4d54ca17bacff7e519e6"
---
**Decision:** Poll AIS every five seconds and treat the nearest aid-to-navigation report as lamp status.

**Why:** We wanted a live feed without waiting on keepers.

**Consequences:** The board lied whenever AIS lagged or an AtoN transponder was offline.

**How to verify:** (superseded — see dec-20260912-a1b2)
