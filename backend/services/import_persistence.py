from backend.models import PersistentData, Problem, Stop


def apply_persistent_solutions(session):
    """
    Apply previously saved persistent solutions and notes to newly created data.

    - For each PersistentData without note_type: apply solutions to matching Problem rows
    - Notes are no longer applied to entity tables; notes are per-user in user_notes
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

    session.commit()
    print(f"Applied {applied_count} persistent solutions from previous imports")
    print(f"Skipped {skipped_count} persistent solutions (stops or problems no longer exist)")
    print("Per-user notes are stored in user_notes and not applied to entity tables.")


