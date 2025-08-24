## Persistent Data (Solutions and Notes)

Preserve validated solutions and notes across imports. Unified system for problems and notes on both ATLAS and OSM sides.

### Database

Single table `persistent_data` stores solutions and notes:
- `sloid` (nullable), `osm_node_id` (nullable)
- `problem_type` in {'distance','unmatched','attributes','duplicates'} or NULL for notes
- `solution` (for problems)
- `note_type` in {'atlas','osm'} or NULL for problems
- `note` (for persistent notes)
- `created_by_user_id`, `created_by_user_email` (author attribution)
- `created_at`, `updated_at` timestamps
- Unique on (`sloid`,`osm_node_id`,`problem_type`,`note_type`)

### Flow

1) Import writes new stops and problems; `persistent_data` remains intact
2) `apply_persistent_solutions()` in [backend/services/import_persistence.py](../backend/services/import_persistence.py) applies persisted solutions and notes to the fresh data
3) UI allows saving solutions/notes and making them persistent

Key endpoints (see [backend/blueprints/problems.py](../backend/blueprints/problems.py))
- Solutions: `/api/save_solution`, `/api/make_solution_persistent`, `/api/check_persistent_solution`
- Notes: `/api/save_note/atlas`, `/api/save_note/osm`, `/api/make_note_persistent/<atlas|osm>`, `/api/check_persistent_note/<atlas|osm>`
- Lists/manage: `/api/persistent_data`, `/api/non_persistent_data`
- Admin ops: `/api/make_all_persistent`, `/api/clear_all_persistent`, `/api/clear_all_non-persistent`

See also: [PERMISSIONS.md](./PERMISSIONS.md) for who can access these endpoints.

### Change scenarios

- Stop still exists, same problem → solution is re-applied
- Stop exists, problem resolved → nothing to apply; solution kept for future runs
- Stop removed → nothing to apply; solution retained
- New problem type → previous solution does not apply; solve and persist if desired

### Benefits and cautions

- Can preserves context of why decisions where made wiht notes
- Persistent solutions can be updated or removed
- Periodically review persistent items
- Notes apply regardless of attribute changes

