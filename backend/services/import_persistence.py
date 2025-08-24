from backend.models import PersistentData, Problem, Stop, AtlasStop, OsmNode


def apply_persistent_solutions(session):
    """
    Apply previously saved persistent solutions and notes to newly created data.

    - For each PersistentData without note_type: apply solutions to matching Problem rows
    - For note_type == 'atlas': apply notes to AtlasStop rows
    - For note_type == 'osm': apply notes to OsmNode rows
    """
    print("Applying persistent solutions from previous imports...")

    # Get all persistent solutions for problems (note_type is None)
    persistent_solutions = session.query(PersistentData).filter(
        PersistentData.note_type.is_(None)
    ).all()
    applied_count = 0
    skipped_count = 0

    for ps in persistent_solutions:
        # Find matching stops in the new data
        matching_stops = session.query(Stop).filter(
            (Stop.sloid == ps.sloid) | (Stop.osm_node_id == ps.osm_node_id)
        ).all()

        if not matching_stops:
            print(f"  - No matching stop found for persistent solution: sloid={ps.sloid}, osm_node_id={ps.osm_node_id}")
            skipped_count += 1
            continue

        for stop in matching_stops:
            # Find problems of the same type for this stop
            problem = session.query(Problem).filter(
                Problem.stop_id == stop.id,
                Problem.problem_type == ps.problem_type
            ).first()

            if problem:
                problem.solution = ps.solution
                problem.is_persistent = True
                applied_count += 1
            else:
                print(
                    f"  - Stop exists but problem type '{ps.problem_type}' no longer detected for: "
                    f"sloid={stop.sloid}, osm_node_id={stop.osm_node_id}"
                )
                skipped_count += 1

    # Apply persistent ATLAS notes
    print("Applying persistent ATLAS notes...")
    atlas_notes = session.query(PersistentData).filter(
        PersistentData.note_type == 'atlas',
        PersistentData.sloid.isnot(None)
    ).all()

    atlas_notes_applied = 0
    atlas_notes_skipped = 0

    for note_record in atlas_notes:
        atlas_stop = session.query(AtlasStop).filter(
            AtlasStop.sloid == note_record.sloid
        ).first()

        if atlas_stop:
            atlas_stop.atlas_note = note_record.note
            atlas_stop.atlas_note_is_persistent = True
            atlas_notes_applied += 1
        else:
            print(f"  - ATLAS stop not found for sloid={note_record.sloid}, skipping note application")
            atlas_notes_skipped += 1

    # Apply persistent OSM notes
    print("Applying persistent OSM notes...")
    osm_notes = session.query(PersistentData).filter(
        PersistentData.note_type == 'osm',
        PersistentData.osm_node_id.isnot(None)
    ).all()

    osm_notes_applied = 0
    osm_notes_skipped = 0

    for note_record in osm_notes:
        osm_node = session.query(OsmNode).filter(
            OsmNode.osm_node_id == note_record.osm_node_id
        ).first()

        if osm_node:
            osm_node.osm_note = note_record.note
            osm_node.osm_note_is_persistent = True
            osm_notes_applied += 1
        else:
            print(f"  - OSM node not found for osm_node_id={note_record.osm_node_id}, skipping note application")
            osm_notes_skipped += 1

    session.commit()
    print(f"Applied {applied_count} persistent solutions from previous imports")
    print(f"Skipped {skipped_count} persistent solutions (stops or problems no longer exist)")
    print(f"Applied {atlas_notes_applied} persistent ATLAS notes, skipped {atlas_notes_skipped}")
    print(f"Applied {osm_notes_applied} persistent OSM notes, skipped {osm_notes_skipped}")


