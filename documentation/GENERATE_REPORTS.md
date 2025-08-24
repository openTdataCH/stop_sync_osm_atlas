### Generating Reports

Use the Reports page to export insights about ATLAS–OSM matching. Reports can be downloaded as PDF (nicely formatted) or CSV (for spreadsheets/analysis).

- A modal/section lets you configure the report and start generation.

### Report categories
- **Distance**
- **Unmatched**: You can include ATLAS, OSM, or both sources.
- **Problems**:  Can be filtered by type, priority, and status.

### Filters and options
- **ATLAS operator**: Filter to one or more operators.
- **Number of entries**: All, or Up to N.
- **Sort order**:
  - Distance: operator A→Z/Z→A, distance ↑/↓
  - Unmatched: operator A→Z/Z→A
  - Problems: operator A→Z/Z→A, priority ↑/↓
- **Format**: PDF or CSV.
![Reports options](documentation/images/ReportsOptions.png)

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
![Reports progress bar](documentation/images/ReportsProgress.png)

### Limits
- Downloads are limited to 20 reports per IP per day to ensure fair use.




