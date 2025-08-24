### Generating Reports

Use the Reports page to export insights about ATLAS–OSM matching. Reports can be downloaded as PDF (nicely formatted) or CSV (for spreadsheets/analysis).

### Where to find it
- From the map page, click the Generate Report button, or open `/reports` directly.
- A modal/section lets you configure the report and start generation.

### Report categories
- **Distance**: Matched stops with distance and matching method. Useful for spotting poor matches.
- **Unmatched**: Stops that are present only in ATLAS or only in OSM. You can include ATLAS, OSM, or both sources.
- **Problems**: Detected data issues with optional solution text. Can be filtered by type, priority, and status.

### Filters and options
- **ATLAS operator**: Filter to one or more operators.
- **Number of entries**: All, or Up to N.
- **Sort order**:
  - Distance: operator A→Z/Z→A, distance ↑/↓
  - Unmatched: operator A→Z/Z→A
  - Problems: operator A→Z/Z→A, priority ↑/↓
- **Format**: PDF or CSV.

### Category-specific options
- **Unmatched**: Include sources — ATLAS, OSM (both by default).
- **Problems**:
  - Problem types: distance, unmatched, attributes, duplicates
  - Priorities: P1, P2, P3
  - Status: solved, unsolved

### Running and downloading
1. Click Generate to start. Report generation runs asynchronously.
2. A progress overlay shows processed entries, percentage, and ETA. You can cancel at any time.
3. When finished, a Download button appears. The file is served once and then cleaned up.

Tip: Prefer CSV for large datasets; PDF is better for sharing/printing.

### Limits
- Downloads are limited to 20 reports per IP per day to ensure fair use.
- Background endpoints also have reasonable rate limits; if you hit a limit, wait and try again.

### Power users: auto-run via URL
Open the Reports page with preset options and auto-start generation:

`/reports?auto=1&report_type=distance&format=csv&limit=100&sort=distance_desc`

Supported presets: `report_type` (distance|unmatched|problems), `format` (pdf|csv), `limit` (number), `sort` (one of the UI options). The operator filter is selected via the on-page dropdown.


