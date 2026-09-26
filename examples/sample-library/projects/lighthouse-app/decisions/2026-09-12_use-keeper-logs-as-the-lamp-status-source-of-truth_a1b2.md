---
id: dec-20260912-a1b2
type: decision
title: Use keeper logs as the lamp-status source of truth
status: current                 # proposed | current | superseded | retired
project: lighthouse-app
scope: {lane: harbor-board, team: keepers}
created: 2026-09-12T09:00:00Z
author: mara
approved_by: "mara — \"files first, the light is what the keeper signed\""
evidence:
  - {ref: "note:keeper log 2026-09-12"}
  - {ref: "url:https://www.iala.int/"}
  - {ref: "project:BRIEF.md"}
supersedes: [dec-20260905-c0de]
superseded_by: null
review_by: 2027-03-11
tags: [lamp, keeper-log, ais]
sensitivity: normal                 # normal | private
body_sha256: "b8c437f51c86f2c028a51cb213f5ef7017f4565368b55a2467b2da155523c799"
---
**Decision:** Lamp status on the harbor board is taken from keeper logs, not from AIS.

**Why:** AIS reports the ship, not the light. Keepers already record the character, eclipse, and outages in the log. The board must show what the light is doing, even when a vessel's transponder is dark.

**Consequences:** The keeper log is a first-class input. AIS remains a traffic overlay. If the log is late, the board shows the last signed character and a stale badge.

**How to verify:** With AIS off, posting a keeper log line updates the lamp panel within one refresh.
