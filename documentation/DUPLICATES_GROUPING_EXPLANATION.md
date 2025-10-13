## Why ATLAS (P2) items can appear inside OSM duplicate groups

### TL;DR
- Duplicate Problems are created with a side-specific priority:
  - **ATLAS-side duplicates → P2**
  - **OSM-side duplicates → P3**
- The grouping code in the API puts each Problem into OSM and/or ATLAS groups based only on what identifiers exist on the stop (presence of `osm_node_id`/`osm_local_ref` vs `sloid`/`atlas_designation`), without checking which side actually caused the duplicate.
- Because matched stops typically have both ATLAS and OSM identifiers, a single ATLAS-side duplicate (P2) can be included in an OSM-keyed group. When group priority is computed as the min of member priorities, this contaminates the OSM group with **P2**.

---

### 1) Where priorities P2 / P3 come from (data import)
During import, duplicates are detected and Problems are created per stop with side-specific priorities:

```556:568:import_data_db.py
# In matched records
if osm_node_id and str(osm_node_id) in duplicate_osm_node_ids:
    stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=3))
    stop_record.atlas_duplicate_sloid = True
elif sloid and str(sloid) in duplicate_sloid_map:
    stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=2))
    try:
        stop_record.atlas_duplicate_sloid = str(duplicate_sloid_map.get(str(sloid)))
    except Exception:
        stop_record.atlas_duplicate_sloid = 'dup'
```

```805:812:import_data_db.py
# In unmatched ATLAS records
if sloid and str(sloid) in duplicate_sloid_map:
    stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=2))
```

```874:877:import_data_db.py
# In unmatched OSM records
if osm_node_id and str(osm_node_id) in duplicate_osm_node_ids:
    stop_record.problems.append(Problem(problem_type='duplicates', solution=None, is_persistent=False, priority=3))
```

Result:
- ATLAS-side duplicates → Problems with `priority = 2` (P2)
- OSM-side duplicates → Problems with `priority = 3` (P3)

Note: For matched stops, a single `Stop` has both ATLAS and OSM identifiers (e.g., `sloid` and `osm_node_id`).

---

### 2) How the API groups duplicates today (response building)
The `/api/problems` endpoint builds two separate groupings:
  - OSM groups keyed by `(uic_ref, osm_local_ref)`
  - ATLAS groups keyed by `(uic_ref, atlas_designation)`

Membership is based on the presence of fields, not on the duplicate side:

```79:93:backend/blueprints/problems.py
for pr in duplicate_problems:
    st = pr.stop
    if st is None:
        continue
    # OSM-side grouping: (uic_ref, local_ref)
    osm_details = st.osm_node_details
    if st.osm_node_id and osm_details and osm_details.osm_local_ref:
        key = (str(st.uic_ref or ''), str(osm_details.osm_local_ref or '').lower())
        osm_groups[key].append(pr)
    # ATLAS-side grouping: (uic_ref, designation)
    atlas_details = st.atlas_stop_details
    if getattr(st, 'sloid', None) and atlas_details and getattr(atlas_details, 'atlas_designation', None):
        atlas_key = (str(st.uic_ref or ''), str(atlas_details.atlas_designation or '').strip().lower())
        atlas_groups[atlas_key].append(pr)
```

Then a group-wide priority is derived from its members using `min(priorities)`:

```129:143:backend/blueprints/problems.py
# OSM group priority from members
group_priority = min(priorities) if priorities else 3
```

```186:201:backend/blueprints/problems.py
# ATLAS group priority from members
group_priority = min(priorities) if priorities else 2
```

Implication:
- If a `Problem` has both ATLAS and OSM identifiers (common for matched stops), it will be added to both group spaces.
- An ATLAS-side duplicate (`priority = 2`) can enter an OSM group if the stop has `osm_node_id` and a non-empty `osm_local_ref`.
- The OSM group’s computed priority becomes `min(...) = 2`, producing a P2 OSM group even though OSM-side duplicates should be P3.

---

### 3) Why this shows as inconsistent UI
- Groups labeled as "OSM" may display P2 because of the contaminated `min(priorities)`.
- The same mixed membership also causes UX mismatches (e.g., "source: OSM" label while clicking reveals an ATLAS popup), since the included `Stop` objects carry both sides’ identifiers and the UI reacts to whichever identifier it uses for that interaction.

---

### 4) Minimal, low-risk fix (keep groups side-pure)
Filter members when building groups so that each group only contains Problems whose duplicate side matches the group type:
- OSM groups: include only `priority == 3`
- ATLAS groups: include only `priority == 2`

Sketch of the change:

```python
# inside the duplicates-building loop in backend/blueprints/problems.py
prio = getattr(pr, 'priority', None)

# OSM grouping: keep only OSM-side duplicates (P3)
if st.osm_node_id and osm_details and osm_details.osm_local_ref and prio == 3:
    key = (str(st.uic_ref or ''), str(osm_details.osm_local_ref or '').lower())
    osm_groups[key].append(pr)

# ATLAS grouping: keep only ATLAS-side duplicates (P2)
if getattr(st, 'sloid', None) and atlas_details and getattr(atlas_details, 'atlas_designation', None) and prio == 2:
    atlas_key = (str(st.uic_ref or ''), str(atlas_details.atlas_designation or '').strip().lower())
    atlas_groups[atlas_key].append(pr)
```

Effects:
- OSM groups cannot contain P2 members; their priority will never be polluted to P2.
- ATLAS groups contain only P2 members, as intended.
- UI labels, group priorities, and which popup opens become consistent.

---

### 5) Is having two separate groups a problem?
No. After applying side-pure membership:
- An ATLAS group communicates that ATLAS has duplicates for a given `(uic_ref, designation)`.
- An OSM group communicates that OSM has duplicates for a given `(uic_ref, local_ref)`.
- You may see both groups for the same place; that’s accurate and informative.

Only if you want a single, merged "duplicates around here" entity would you consider a more complex composite grouping. That’s a UX choice and not required to fix the inconsistencies described above.


