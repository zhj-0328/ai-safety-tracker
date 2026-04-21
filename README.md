---
title: AI Safety Tracker
emoji: 🛡️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# AI Safety Tracker

Track recent papers from teacher-recommended CCF network and information security journals.

Current sources are organized from the CCF recommended catalog for the network and information security area:

- CCF A journals: `TDSC`, `TIFS`, `Journal of Cryptology`
- CCF B journals: `TOPS`, `Computers & Security`, `Designs, Codes and Cryptography`, `Journal of Computer Security`

The tracker only keeps papers published within the last year so the page stays frontier-focused.

This Space runs a lightweight Python web service and exposes a source-based paper tracking UI.

## Easier Maintenance

The project is now organized so future updates mostly happen in configuration files:

- [config/sources.py](./config/sources.py)
  Edit source URLs, CCF tiers, ISSNs, and source descriptions here.
- [config/keywords.py](./config/keywords.py)
  Edit AI safety / security related keywords here.

In most cases:

- add or remove a source: edit `config/sources.py`
- change keyword coverage: edit `config/keywords.py`
- update the one-year journal pool: edit `config/sources.py`

This means you usually do not need to touch [server.py](./server.py) for routine maintenance.
