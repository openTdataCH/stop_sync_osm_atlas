"""Application-owned half of the versioned pipeline progress contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable


PROGRESS_SCHEMA_VERSION = 1
PROGRESS_STATUSES = {"waiting", "running", "complete", "reused", "skipped", "failed"}
TERMINAL_STATUSES = PROGRESS_STATUSES - {"waiting", "running"}


class ProgressValidationError(ValueError):
    """Invalid public telemetry; never a failure of the underlying work."""


@dataclass(frozen=True)
class ProgressStage:
    id: str
    parent_id: str | None
    phase: str
    label: str
    description: str
    order: int
    progress_kind: str = "indeterminate"


PIPELINE_PHASE_STAGES = (
    ProgressStage("source_check", None, "source_check", "Check sources", "Check source freshness and reusable inputs.", 10),
    ProgressStage("atlas", None, "atlas", "Prepare ATLAS", "Prepare the official source-stop snapshot.", 20),
    ProgressStage("timetable", None, "timetable", "Prepare timetable data", "Prepare GTFS identities and routes.", 30),
    ProgressStage("osm", None, "osm", "Prepare OpenStreetMap", "Download and normalize the OSM snapshot.", 40),
    ProgressStage("stop_matching", None, "stop_matching", "Stop matching", "Match stops and detect stop-level data problems.", 50),
    ProgressStage("route_matching", None, "route_matching", "Route matching", "Compare route families and itineraries.", 60),
    ProgressStage("bundle", None, "bundle", "Build result bundle", "Create the validated engine result snapshot.", 70),
    ProgressStage("database", None, "database", "Stage database", "Prepare and load application database records.", 80),
    ProgressStage("publish", None, "publish", "Publish dataset", "Atomically publish the snapshot and analytics.", 90),
)

APPLICATION_PROGRESS_STAGES = (
    ProgressStage(
        "database.validate", "database", "database", "Validate the result bundle",
        "Verify the bundle schema, checksums and entity references.", 10,
    ),
    ProgressStage(
        "database.prepare", "database", "database", "Prepare application records",
        "Project engine results into application-owned database rows.", 20,
    ),
    ProgressStage(
        "database.load", "database", "database", "Load and index the staged database",
        "Load a private staging schema, build indexes and analyze its tables.", 30,
    ),
    ProgressStage(
        "publish.swap", "publish", "publish", "Publish the new dataset",
        "Atomically swap the staged tables into the public schema.", 10,
    ),
    ProgressStage(
        "publish.analytics", "publish", "publish", "Generate analytics",
        "Generate statistics and metadata for the newly published snapshot.", 20,
    ),
)


def initial_progress_plan() -> list[dict[str, Any]]:
    return [asdict(item) for item in (*PIPELINE_PHASE_STAGES, *APPLICATION_PROGRESS_STAGES)]


def normalize_stage_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Progress stage definitions must be objects")
    stage_id = value.get("id")
    parent_id = value.get("parent_id")
    phase = value.get("phase")
    label = value.get("label")
    description = value.get("description")
    order = value.get("order")
    progress_kind = value.get("progress_kind", "indeterminate")
    if not all(isinstance(item, str) and item for item in (stage_id, phase, label, description)):
        raise ValueError("Progress stages require nonempty id, phase, label and description")
    if parent_id is not None and not isinstance(parent_id, str):
        raise ValueError(f"Invalid parent for progress stage {stage_id}")
    if type(order) is not int:
        raise ValueError(f"Progress stage {stage_id} requires an integer order")
    if progress_kind not in ("indeterminate", "determinate"):
        raise ValueError(f"Unsupported progress kind for {stage_id}: {progress_kind}")
    return {
        "id": stage_id,
        "parent_id": parent_id,
        "phase": phase,
        "label": label,
        "description": description,
        "order": order,
        "progress_kind": progress_kind,
    }


def validate_progress_plan(stages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_stage_spec(item) for item in stages]
    ids = [item["id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("Progress stage IDs must be unique")
    known = set(ids)
    by_id = {item["id"]: item for item in normalized}
    for item in normalized:
        parent_id = item["parent_id"]
        if parent_id is None and (item["id"] != item["phase"] or item["id"] not in {s.id for s in PIPELINE_PHASE_STAGES}):
            raise ValueError(f"Unknown progress phase: {item['id']}")
        if parent_id is not None and parent_id not in known:
            raise ValueError(f"Unknown parent {parent_id!r} for progress stage {item['id']}")
        if parent_id is not None and item["phase"] not in known:
            raise ValueError(f"Unknown phase {item['phase']!r} for progress stage {item['id']}")
        if parent_id is not None and parent_id != item["phase"]:
            raise ValueError(f"Progress substages must be direct children of their phase: {item['id']}")
        if parent_id is not None and by_id[item["phase"]]["parent_id"] is not None:
            raise ValueError(f"Progress phase must be a root stage: {item['phase']}")
    return normalized


def merge_progress_plan(current: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {item["id"]: normalize_stage_spec(item) for item in current}
    seen = set()
    for item in incoming:
        normalized = normalize_stage_spec(item)
        if normalized["id"] in seen:
            raise ValueError("Progress stage IDs must be unique")
        seen.add(normalized["id"])
        existing = merged.get(normalized["id"])
        if existing is not None and existing != normalized:
            raise ValueError(f"Progress stage definition changed during a run: {normalized['id']}")
        merged[normalized["id"]] = normalized
    return validate_progress_plan(merged.values())


validate_progress_plan(initial_progress_plan())


def elapsed(started_at: str | None, now: str) -> float:
    if not started_at:
        return 0.0
    try:
        started, ended = datetime.fromisoformat(started_at), datetime.fromisoformat(now)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)
        return round(max(0.0, (ended - started).total_seconds()), 3)
    except (TypeError, ValueError):
        return 0.0


def phase_fields(current: dict, phase: str, message: str, now: str, **fields) -> dict:
    """Legacy phase projection, shared by runner and structured child events."""
    history = list(current.get("phase_history") or [])
    previous = current.get("phase")
    started = current.get("phase_started_at")
    if previous and previous not in {"idle", "failed", phase} and started:
        history.append({"phase": previous, "started_at": started, "finished_at": now,
                        "duration_seconds": elapsed(started, now)})
    outcomes = dict(current.get("phase_outcomes") or {})
    outcomes.pop(phase, None)
    history = [entry for entry in history if not (
        entry.get("phase") == phase and entry.get("status") in {"reused", "skipped"})]
    return dict(status="running", phase=phase, message=message,
                phase_started_at=started if previous == phase and started else now,
                phase_history=history, phase_outcomes=outcomes, **fields)


def project_stage_states(current: dict) -> dict:
    """Root states are a projection, never an independently maintained lifecycle."""
    states = {key: dict(value) for key, value in (current.get("stage_states") or {}).items()}
    if not current.get("stage_plan"):
        return states
    history = {entry["phase"]: entry for entry in current.get("phase_history", [])}
    for root in PIPELINE_PHASE_STAGES:
        children = [states.get(spec["id"], {"status": "waiting"})
                    for spec in current.get("stage_plan", []) if spec["parent_id"] == root.id]
        statuses = {child["status"] for child in children}
        entry = dict(history.get(root.id) or {})
        entry.pop("phase", None)
        outcome = (current.get("phase_outcomes") or {}).get(root.id)
        if "failed" in statuses or (current.get("status") == "failed" and current.get("failed_phase") == root.id):
            status = "failed"
        elif outcome:
            status = outcome
        elif children and statuses <= TERMINAL_STATUSES:
            status = next(iter(statuses)) if len(statuses) == 1 else "complete"
        elif "running" in statuses or (current.get("status") == "running" and current.get("phase") == root.id):
            status = "running"
            entry = {"started_at": current.get("phase_started_at")}
        elif not children and entry:
            status = entry.get("status", "complete")
        else:
            status = "waiting"
        if children and status in TERMINAL_STATUSES:
            starts = [child["started_at"] for child in children if child.get("started_at")]
            ends = [child["finished_at"] for child in children if child.get("finished_at")]
            if starts and ends:
                entry.update(started_at=min(starts), finished_at=max(ends),
                             duration_seconds=round(sum(child.get("duration_seconds") or 0.0 for child in children), 3))
        states[root.id] = dict(entry, status=status)
    return states


def _number(value, name, *, integer=False):
    try:
        valid = type(value) in ((int,) if integer else (int, float)) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ProgressValidationError(f"{name} must be a finite nonnegative {'integer' if integer else 'number'}")
    return value


def validate_event(payload: Any, current: dict, *, owner: str | None = None) -> tuple[dict, list[dict]]:
    """Validate everything before returning a candidate plan; no side effects."""
    if not isinstance(payload, dict) or type(payload.get("progress_schema_version")) is not int or payload["progress_schema_version"] != PROGRESS_SCHEMA_VERSION:
        raise ProgressValidationError("Unsupported pipeline progress schema version")
    event = payload.get("event")
    if event not in ("pipeline_plan", "stage_started", "stage_progress", "stage_finished", "stage_failed", "stage_outcome"):
        raise ProgressValidationError(f"Unsupported pipeline progress event: {event}")
    result = dict(payload)
    incoming = []
    if event == "pipeline_plan":
        incoming = payload.get("stages")
        if not isinstance(incoming, list):
            raise ProgressValidationError("Pipeline progress plan must contain a stage list")
    else:
        stage_id = payload.get("stage_id")
        if not isinstance(stage_id, str) or not stage_id:
            raise ProgressValidationError("Pipeline progress events require a stage_id")
        if payload.get("stage_spec") is not None:
            incoming = [payload["stage_spec"]]
        if event == "stage_outcome" and payload.get("outcome") not in ("reused", "skipped"):
            raise ProgressValidationError("Unsupported progress stage outcome")
        for key in ("seconds", "processed", "total"):
            if payload.get(key) is not None:
                result[key] = _number(payload[key], key, integer=key != "seconds")
        if result.get("processed") is not None and result.get("total") is not None and result["processed"] > result["total"]:
            raise ProgressValidationError("processed cannot exceed total")
        if payload.get("counters") is not None:
            counters = payload["counters"]
            if not isinstance(counters, dict) or not all(isinstance(key, str) for key in counters):
                raise ProgressValidationError("counters must be an object with string keys")
            result["counters"] = {key: _number(value, key, integer=True) for key, value in counters.items()}
    try:
        incoming = [normalize_stage_spec(spec) for spec in incoming]
        if event != "pipeline_plan" and incoming and incoming[0]["id"] != result["stage_id"]:
            raise ProgressValidationError("stage_spec.id must equal stage_id")
        plan = merge_progress_plan(current.get("stage_plan") or initial_progress_plan(), incoming)
    except ValueError as exc:
        raise ProgressValidationError(str(exc)) from exc
    by_id = {spec["id"]: spec for spec in plan}
    checked = incoming
    if event != "pipeline_plan":
        spec = by_id.get(result["stage_id"])
        if spec is None or spec["parent_id"] is None:
            raise ProgressValidationError(f"Unknown progress substage: {result['stage_id']}")
        checked = [*incoming, spec]
    if owner == "engine" and any(spec["parent_id"] is None or spec["phase"] in {"database", "publish"} for spec in checked):
        raise ProgressValidationError("Engine events must describe engine-owned substages")
    return result, plan


def apply_progress_event(current: dict, payload: dict, now: str, *, owner=None, run_id=None) -> dict:
    """Return a validated state patch. Terminal runs and stale writers are inert."""
    event, plan = validate_event(payload, current, owner=owner)
    if current.get("status") != "running" or current.get("finished_at") or (run_id is not None and current.get("run_id") != run_id):
        return {}
    states = {key: dict(value) for key, value in current.get("stage_states", {}).items()}
    for spec in plan:
        inherited = (current.get("phase_outcomes") or {}).get(spec["phase"])
        states.setdefault(spec["id"], {"status": inherited or "waiting", **(
            {"started_at": now, "finished_at": now, "duration_seconds": 0.0} if inherited else {})})
    fields = dict(stage_plan=plan, stage_states=states, progress_schema_version=PROGRESS_SCHEMA_VERSION)
    kind = event["event"]
    if kind != "pipeline_plan":
        stage_id = event["stage_id"]
        spec = next(spec for spec in plan if spec["id"] == stage_id)
        previous = states[stage_id]
        # Repeated terminal events and delayed heartbeats must not restart work.
        if previous["status"] in TERMINAL_STATUSES and not (
            kind == "stage_started" and previous["status"] in {"reused", "skipped"}):
            return {}
        state = dict(previous)
        if kind in {"stage_started", "stage_progress"}:
            state = dict(status="running", started_at=(previous.get("started_at") if previous["status"] == "running" else None) or now)
            state.update({key: previous[key] for key in ("processed", "total", "counters") if key in previous})
            fields.update(phase_fields(current, spec["phase"], spec["label"], now,
                                       processed=event.get("processed"), total=event.get("total"), eta_seconds=None))
        else:
            status = event["outcome"] if kind == "stage_outcome" else "complete" if kind == "stage_finished" else "failed"
            state.update(status=status, started_at=previous.get("started_at") or now, finished_at=now,
                         duration_seconds=event["seconds"] if event.get("seconds") is not None else elapsed(previous.get("started_at"), now))
            if kind == "stage_outcome":
                state.update(started_at=now, duration_seconds=0.0)
            if event.get("error"):
                state["error"] = str(event["error"])
        for key in ("processed", "total", "counters"):
            if event.get(key) is not None:
                state[key] = event[key]
        if state.get("processed") is not None and state.get("total") is not None and state["processed"] > state["total"]:
            raise ProgressValidationError("processed cannot exceed total")
        states[stage_id] = state
        if stage_id == "publish.swap" and state["status"] == "complete":
            fields["dataset_published"] = True
        siblings = [states[s["id"]]["status"] for s in plan if s["parent_id"] == spec["phase"]]
        if kind == "stage_outcome" and set(siblings) == {event["outcome"]}:
            phase = spec["phase"]
            fields["phase_outcomes"] = dict(current.get("phase_outcomes") or {}, **{phase: event["outcome"]})
            fields["phase_history"] = [h for h in current.get("phase_history", []) if h.get("phase") != phase or h.get("status") not in {"reused", "skipped"}]
            fields["phase_history"].append(dict(phase=phase, **state))
    fields["stage_states"] = project_stage_states(dict(current, **fields))
    return fields


def finalize_stage_states(current: dict, now: str, *, failed: bool) -> tuple[dict, list[str]]:
    """Preserve finished work; close active or never-started children honestly."""
    states = {key: dict(value) for key, value in current.get("stage_states", {}).items()}
    warnings = []
    for spec in current.get("stage_plan", []):
        if spec["parent_id"] is None:
            continue
        state = states.get(spec["id"], {"status": "waiting"})
        status = state["status"]
        if status in {"waiting", "running"}:
            reason = "Run stopped before this work finished" if failed else "No completion event was received"
            state.update(status="failed" if status == "running" else "skipped", finished_at=now,
                         duration_seconds=elapsed(state.get("started_at"), now), reason=reason)
            states[spec["id"]] = state
        if not failed and (status in {"waiting", "running", "failed"}):
            warnings.append(f"{spec['label']}: {state.get('error') or state.get('reason') or 'failed'}")
    return states, warnings
