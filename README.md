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

Track frontier AI safety papers by source, including:

- S&P / NDSS / USENIX Security / CCS
- ICML / CVPR
- arXiv feeds for Security of AI and AI for Security
- Anthropic / Google DeepMind safety-related research pages

This Space runs a lightweight Python web service and exposes a source-based paper tracking UI.

## Easier Maintenance

The project is now organized so future updates mostly happen in configuration files:

- [config/sources.py](./config/sources.py)
  Edit source URLs, descriptions, source categories, and arXiv queries here.
- [config/keywords.py](./config/keywords.py)
  Edit AI safety related keywords here.

In most cases:

- add or remove a source: edit `config/sources.py`
- change keyword coverage: edit `config/keywords.py`
- adjust arXiv search scope: edit `config/sources.py`

This means you usually do not need to touch [server.py](./server.py) for routine maintenance.
