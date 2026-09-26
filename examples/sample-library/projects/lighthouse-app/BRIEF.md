# Lighthouse App

**Purpose:** Harbor dashboard that coordinates lamp status, fog signals, and vessel traffic for a fictional headland light.

**Generated:** 2026-09-26T16:14:46Z

## Current decisions

- **Use keeper logs as the lamp-status source of truth** — Decision: Lamp status on the harbor board is taken from keeper logs, not from AIS.

## Open requirements

- **Fog-signal schedule must work unplugged** — Requirement: The fog-signal schedule can be read and updated with the SSD unplugged and with no network.
- **Show live lamp character on the harbor board** — Requirement: The harbor board shows the current lamp character (for example Fl W 15s), the time it was signed, and wh...

## Key facts

- Fact: Mean tidal range at the headland is 3.2 metres.
- Fact: The headland lamp character is Fl W 15s — a white flash every 15 seconds.

## Recent returns

- **Keeper trial 20 Sep 2026** — Return: First keeper trial, 20 September 2026.

## Review due

0 records due on or before 2026-09-26.
Next review 2026-10-14.

## Glossary (short)

- **character** — The published flash pattern of a light, written in the light-list notation (for example Fl W 15s).
- **watch** — A four-hour keeper shift. The harbor board groups log lines by watch.
