# Manual Matching – Design and Implementation

## Goals

- Provide a simple, reliable way to manually match an unmatched ATLAS entry with an OSM node directly from the Problems page.
- Persist these decisions so they survive data imports and are applied at the beginning of the next matching run.
- Make manual matches discoverable via filters and clearly visible on maps.

## UX Flow

1. On `Problems` page, when viewing an `unmatched` problem, click “Match to”. If “See other markers” is off, it is automatically enabled to show nearby opposite‑dataset entries.
2. A persistent banner appears: “Select an entry on the opposite dataset…”, with Cancel.
3. Open an opposite‑dataset popup. Its button reads “Match to this entry”. Click it to finalize.
4. The app calls `POST /api/manual_match` with `{ atlas_stop_id, osm_stop_id, make_persistent }`.
5. If Auto‑persist is ON, the match is persisted immediately; otherwise it is temporary.
6. The problems list refreshes; the pair becomes `matched` with `match_type='manual'`.

## Backend API

- `POST /api/manual_match` (in `backend/app_search.py`)
  - Input: `atlas_stop_id`, `osm_stop_id`, `make_persistent` (bool)
  - Behavior:
    - Sets both rows to `stop_type='matched'` and `match_type='manual'`.
    - Links ids in both directions (`sloid` and `osm_node_id` and coordinates copied for context).
    - If `make_persistent=true`, sets `Stop.manual_is_persistent=True` and writes a `PersistentData` record with `{problem_type:'unmatched', solution:'manual'}` for `(sloid, osm_node_id)`.
  - Response: `{ success, message, is_persistent }`.

## Database Changes

- `stops.manual_is_persistent BOOLEAN DEFAULT FALSE` – marks that this `manual` match is persisted.
- No new tables required. Manual persistence is stored in `persistent_data` as a problem solution:
  - `(sloid, osm_node_id, problem_type='unmatched', solution='manual')`.

Schema migration is applied automatically by `ensure_schema_updated()`.

## Import Pipeline Integration

In `matching_process/final_pipeline`:
- Before exact/name/distance stages, load `PersistentData` entries where `{problem_type='unmatched', solution='manual'}` and build `manual_pairs`.
- Seed `used_osm_ids_total` with manual node IDs and construct synthetic "manual" match records added first to `all_matches`.
- These pairs are excluded from later automatic matching and appear with `match_type='manual'` in exports.

## Frontend Changes

- Index page: removed legacy Save/Preview buttons and the old `manual-matching.js`. Added “Manage Persistent Data” link.
- Problems page:
  - Action buttons for `unmatched` entries include “Match to”.
  - Clicking “Match to” auto‑enables “See other markers” if it’s off, so the user can pick the other side.
  - Popups for unmatched entries show “Match to”; when a selection is active, opposite‑dataset popups change to “Match to this entry”.
  - Clicking both sides posts to `/api/manual_match`. If auto‑persist is enabled, the match is persisted immediately.
  - Purple connection lines are used consistently; manual matches are purple (dashed if non‑persistent, solid if persistent). The Problems map mirrors the main styling.

## Filtering and Visibility

- You can filter by `match_method=manual` on the main map (`/api/data` already supports it).
- Each `Stop` includes `manual_is_persistent` in `/api/data` payloads for potential UI styling.

## Pros & Cons

Pros:
- Simple, consistent flow integrated into the Problems page.
- Decisions persist across imports and are applied first, preventing conflicting automatic matches.
- Minimal schema change; leverages existing `persistent_data`.

Cons:
- We store persistence in `persistent_data` using `problem_type='unmatched'`, which overloads the table’s semantics (but keeps one store for persistence).
- No explicit conflict resolution UI if a manual pair would collide with another persistent mapping (server trusts latest call).

## Future Enhancements

- Visual distinction on maps for persistent vs. temporary manual matches (solid vs dashed purple) everywhere.
- Conflict checks: prevent multiple different OSM nodes being persisted for the same SLOID (and vice versa).
- Management UI to list and revoke manual matches separately.


