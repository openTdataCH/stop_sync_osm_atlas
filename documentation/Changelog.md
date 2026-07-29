# Changelog

All notable changes to this project will be documented in this page.

---

## Version 0.5

**Released:** July 30th 2026

### New Features
- **Search and filters on GTFS↔SLOID map**
- **See routes on the GTFS↔SLOID map popup** — Like on the main map
- **See duplicates button on popup** — Similar to the "See matches button", easily see the duplicate peers for one ATLAS stop.
- **Enhanced UI for route variants and replacement routes UI**

### Improvements

- **Consolidated frontend code** — Unified map and popup logic across the application.
- **File-backed runtime state** — Docker Compose no longer runs Redis; the app and scheduler communicate through shared JSON files in `data/runtime`.
- **Updated documentation** — Expanded and revised project documentation.
