# Dependency availability and pipeline diagnostics

Status: proposed implementation plan. No runtime or UI changes are implemented by this document.

## Objective

Explain why a pipeline run stopped, which dependency was involved, and whether another attempt is likely to help. Keep the matching engine independently runnable and keep source-specific error detection out of the web application.

The existing stage timeline identifies where work failed. Extend that reporting so a failure can say **“OSM download failed: Overpass returned HTTP 504”** instead of only reporting that the engine command exited with code 1.

UI layout, wording placement, and interaction design remain open. This plan defines the evidence and behavior the UI will be able to consume.

## Motivating incident: October 7, 2026

The supplied logs and screenshot show this sequence:

1. Source checks, ATLAS preparation, GTFS download, timetable preparation, and GTFS-to-ATLAS integration completed.
2. The `osm.download` stage received HTTP 504 from Overpass and failed.
3. The engine raised an exception and exited with code 1.
4. The application subprocess wrapper raised another exception and marked the run failed. Matching and publication did not execute.

These are two tracebacks for one underlying failure. Raising a failure and preserving the previously published dataset is appropriate. The reporting needs improvement:

- The wrapper reports `Step source_check failed` because it uses the initial phase supplied when launching the engine, even though execution has reached `source_files` / `osm.download`.
- The engine already emits `stage_failed` with the original error text. The app stores that text in `stage_states["osm.download"]["error"]`, but its top-level `last_error` contains the generic subprocess failure.
- The Overpass exception includes only the first 400 characters of the response. An HTML prologue can consume that preview before the actual service error appears.
- The approximately 19-minute subprocess duration includes successful preprocessing. The screenshot attributes approximately 43 seconds to the failed Overpass stage.

A 504 identifies an unsuccessful Overpass request. It does not by itself prove that all Overpass servers are down. Overpass can reject a request when its requested resources cannot be accommodated.

## Dependency inventory

### Pipeline data sources

| Dependency | Purpose | Relevant stages | Possible failures |
|---|---|---|---|
| ATLAS through opentransportdata.swiss and its download hosting | Official Swiss stops and platform information | `source_check.remote_sources`, `atlas.prepare`, `atlas.load` | Service unavailable, broken redirects, inaccessible resource, changed CSV/ZIP format, missing columns, invalid values, empty or suspiciously small dataset |
| GTFS through opentransportdata.swiss and its download hosting | Stop identities, timetable patterns, routes and itineraries | `source_check.remote_sources`, `timetable.download`, `timetable.patterns`, `timetable.identities_routes`, `timetable.load`, `timetable.local_feed` | Interrupted or corrupt ZIP, missing files/columns, invalid IDs or relationships, changed Swiss identifiers, stale feed, unavailable timetable-year resource |
| Overpass | OSM public-transport snapshot | `osm.download`, `osm.prepare` | Rate limiting, unavailable capacity, HTTP errors, connection/read timeout, query execution or memory limit, malformed or incomplete XML, empty or stale snapshot |
| Swiss boundary GeoJSON on GitHub | Geographic filtering of stops | Boundary preparation during source checks; ATLAS and GTFS filtering | Download failure when cache is absent, moved resource, invalid JSON/geometry, unexpected boundary contents |

ATLAS and GTFS share a publishing platform. A single hosting incident may affect both. Preserve the dataset identity as well as the service/host involved.

The boundary is normally read from cache. An unavailable GitHub download must not be reported as affecting a run that used a valid local boundary without contacting GitHub.

### Other dependencies and failure domains

| Dependency or environment | Possible failures | Ownership |
|---|---|---|
| Engine executable and engine-to-app contracts | Missing executable/package, unsupported progress version, invalid or incompatible result bundle, missing bundle files or failed checksums | App integration and engine contracts |
| PostgreSQL/PostGIS | Connection failure, authentication/configuration problem, unavailable extension, incompatible schema, lock/statement timeout, failed staging or publication | Application importer |
| Local execution environment | Disk full, insufficient RAM, process killed, permissions failure, corrupted local cache, interrupted worker or container | Component performing the operation; runner handles abrupt termination |
| Map-tile services: OSM, memomaps and Esri | Tile requests fail, time out, or are blocked | Browser/web-app functionality; does not establish a pipeline failure |

Do not classify a missing Python package, disk error, or importer bug as an upstream data-source outage. Links to OSM, ATLAS and Wikidata are also distinct from services actually contacted during processing.

## Failure categories

### 1. Availability and transport

- DNS resolution, connection refusal/reset, or TLS certificate failure.
- Connection timeout, read timeout, interrupted transfer, or excessive redirects.
- HTTP 429 rate limiting or HTTP 5xx service/capacity errors.
- HTTP 401/403 access denied, HTTP 404 missing resource, or an expired signed redirect URL.
- An Overpass query rejected because the server cannot accommodate it, or aborted because it exceeds execution/memory limits.

Temporary failures often benefit from a later retry. Persistent access, URL, certificate, or query problems require investigation. A timeout observed from our server does not prove that the provider is unavailable to everyone.

### 2. Packaging and format

- An HTML error/login page returned where CSV, ZIP, XML, or GeoJSON was expected, including a response with HTTP 200.
- Truncated or invalid archives, missing required archive members, or unexpected packaging.
- Changed CSV delimiter/encoding, malformed records, invalid XML or invalid GeoJSON.
- Overpass runtime-error content or incomplete results that must not be accepted as a complete snapshot merely because the HTTP request succeeded.

Validate the payload before promoting it into a reusable source cache. A successful HTTP response is only a successful transfer, not proof of usable data.

### 3. Schema and value compatibility

- Required columns removed or renamed, or values changing type/meaning.
- Missing identifiers, duplicate identifiers where uniqueness is required, invalid coordinates, or invalid sequences/dates.
- GTFS references to absent stops, trips, or routes.
- Changed identifier conventions, coordinate systems, country codes, or platform-type values.

Additional columns are normally harmless and should remain accepted. Optional missing values and known invalid source rows may be handled by documented filtering rules; reject or warn according to the actual impact rather than failing every imperfect record.

A standards-compliant GTFS feed can still be incompatible with the Swiss integration. Its current filtering requires `original_stop_id` and `didok` in addition to other fields. Identify this as a Swiss integration expectation, rather than claiming those are universal GTFS requirements.

### 4. Freshness, completeness and consistency

- A source or Overpass replica is older than expected.
- A response parses successfully but is empty, unexpectedly small, or missing substantial coverage.
- ATLAS and GTFS are individually valid but out of sync, reducing identifier or route coverage.
- Missing or unreliable HTTP validators prevent freshness verification, force unnecessary rebuilds, or incorrectly suggest that a source is unchanged.

These observations need source-specific rules. ATLAS, timetable feeds and OSM replicas have different update rhythms. An unchanged weekly GTFS feed is not automatically stale because the pipeline runs hourly.

Record counts, source timestamps, and coverage changes as evidence. Start with warnings for uncertain quality regressions. Block publication for established violations of the input contract or configured completeness requirements. Do not silently publish an empty national dataset.

## Reporting principles

1. **Separate stage outcome from dependency observations.** A freshness probe can fail while a subsequent download succeeds. The probe failure is recoverable evidence, not necessarily a failed run.
2. **Report observed facts.** “Overpass returned HTTP 504” is stronger than an unsupported claim that “Overpass is down.”
3. **Preserve the original cause.** Subprocess exit information supplements the failed stage; it must not replace its explanation.
4. **Keep failures, warnings, reuse, and skipped work distinct.** A downstream stage skipped after failure did not succeed. Cache reuse does not establish current remote availability.
5. **Attach observations to a run and timestamp.** A past failure is not a live health check. Keep the last successful publication time separate from source checks and downloads.
6. **Preserve useful diagnostics.** Keep developer tracebacks and technical details in logs, while providing a concise message through the public contract.

## Proposed engine-to-app diagnostic contract

Extend the existing versioned progress contract with structured diagnostics. The engine owns source adapters and classification; the app validates and consumes JSON without importing engine Python modules or parsing tracebacks/HTML.

For a failed stage, retain the existing `error` string for compatibility and add an optional `issue` object. A proposed Overpass diagnostic is:

```json
{
  "event": "stage_failed",
  "progress_schema_version": 2,
  "stage_id": "osm.download",
  "error": "Overpass returned HTTP 504 while downloading OSM data",
  "issue": {
    "origin": "external_source",
    "dependency": "overpass",
    "category": "availability",
    "code": "http_error",
    "severity": "error",
    "message": "Overpass returned HTTP 504 while downloading OSM data",
    "retryable": true,
    "http_status": 504,
    "endpoint": "https://overpass-api.de/api/interpreter"
  }
}
```

This is the diagnostic portion of an event, not a replacement for existing stage metadata and timing fields. Retryability means another attempt may help; it is not a guarantee of recovery or a command to retry immediately.

- Use stable dependency IDs and error codes. Display labels and exception wording must not become identifiers.
- Allow `retryable: null` when the cause is unknown. Identify a more specific code such as `provider_busy` only when the response provides evidence for it.
- Optional details can include attempt counts, missing files/columns, record counts, and a bounded plain-text service explanation. Avoid unbounded records or response bodies.
- Support warnings/observations on successful or nonfatal operations through optional diagnostic fields on existing progress events. Preserve whether an observation was resolved within the run.
- Strip credentials, signed query strings, and sensitive headers from endpoints and details before emitting them. Do not expose raw HTML in the UI.
- Keep unexpected programming exceptions classified as internal/unknown errors. Do not turn every exception inside an adapter into “invalid upstream data.”

Treat this as an additive extension only if producer/consumer compatibility checks confirm it is safe. Document supported optional fields in the engine's progress contract and update app validation/storage. If event types or required semantics change, version the contract and coordinate deployment. The result-bundle schema remains independent.

## Implementation sequence

### Phase 1: Preserve and expose the existing cause

- Prefer the failed engine substage's stored error over the generic subprocess exit message.
- Attribute failure to the actual active/failed stage and its parent phase. Use the launch phase only when no later progress evidence exists.
- Retain subprocess exit code and command in technical logs.
- Extract a bounded, plain-text Overpass error explanation instead of truncating the beginning of an HTML page.
- Keep a fallback for older engines, missing/invalid progress events, and abrupt process termination. Without evidence, report an engine/process failure rather than inventing a dependency cause.

This phase addresses the reported incident without requiring a new health-check service or a UI redesign.

### Phase 2: Add structured source diagnostics

- Define and document the shared JSON fields and stable codes in the engine contract.
- Classify HTTP/network failures at the ATLAS, GTFS, Overpass and boundary acquisition points.
- Distinguish freshness-probe failures from fatal download failures. A completed source-check stage must not discard failed probe observations.
- Extend app validation and stage-state storage to preserve the structured issue. Derive the run-level explanation from that evidence.
- Record retries and recovered failures without making a successful final attempt appear permanently failed.
- Handle application-owned database and publication issues through the same diagnostic shape, with their correct origin and owner.

The current Overpass client retries HTTP 502 and 504, with two retries by default. It does not currently apply that retry loop to all network exceptions or HTTP 429. This plan must not imply that those failures already receive equivalent retries.

### Phase 3: Validate source content and add quality observations

- Validate required columns/files before expensive processing and name missing requirements explicitly.
- Validate Overpass XML and runtime-error content before replacing the previous usable XML snapshot.
- Validate boundary geometry and retain a usable cache when a replacement fails validation.
- Define per-source rules for empty outputs, invalid records, stale snapshots, and substantial count/coverage changes.
- Store sufficient provenance to distinguish remote modification time, download time, processing time, and publication time.
- Preserve existing acquisition checkpoints so a later OSM failure does not discard successful ATLAS/GTFS preparation.

### Phase 4: Decide resilience and UI behavior separately

Use the available evidence to decide whether to add fallback Overpass endpoints, wider retry coverage, or an explicit policy for using older inputs. Do not silently substitute stale data or change matching/publication behavior as part of diagnostic reporting.

The UI can then present the dependency, concise cause, affected stage, observation time, and whether a retry may help. Its layout remains a separate decision. Browser tile failures should be reported through the web-app experience rather than marking a pipeline run failed.

No additional recurring monitoring or remote polling is required for the first phases. Report what the pipeline actually observed before adding independent health checks.

## Validation and acceptance criteria

Use mocked HTTP responses, tiny local CSV/ZIP/XML/GeoJSON fixtures, and synthetic progress streams. These changes should not require a full Swiss pipeline or a live Overpass request to test.

- An Overpass 504 is preserved from engine event to stage state and run-level explanation, with `osm.download` as the affected stage.
- A network timeout remains distinguishable from an HTTP error, with unknown causes represented honestly.
- HTTP 200 containing unusable/error content does not become a successful source snapshot.
- An ATLAS schema mismatch names missing required columns; harmless additional columns remain accepted.
- A GTFS archive missing a required file names the file and identifies GTFS as the dependency.
- A failed freshness probe followed by a successful download can finish successfully while retaining the recovered observation.
- A missing engine executable, unsupported contract, disk error, or database failure is not labelled as an ATLAS/Overpass outage.
- A run failing before publication preserves the previously published dataset and its timestamp. A failure after an actual publication is reported accurately as published-with-warning when appropriate.
- Unknown optional fields and older error-only events receive the documented compatibility behavior. Stale events cannot overwrite another run's state.
- Public diagnostics contain no signed download query strings, credentials, raw HTML, or unbounded payloads.
- A subsequent successful run clears its active failure state while historical observations remain tied to their original runs wherever history is retained.

## Relevant code and documentation

- [Engine progress contract](../engine/documentation/5.3%20Pipeline%20Progress%20Contract.md)
- [Engine progress catalog](../engine/src/public_transport_matcher/progress.py) and [timing/error emission](../engine/src/public_transport_matcher/timing.py)
- [Swiss acquisition and cache checkpoints](../engine/src/public_transport_matcher/adapters/acquisition.py)
- [Overpass acquisition](../engine/src/public_transport_matcher/acquisition/overpass.py)
- [Source freshness probes](../engine/src/public_transport_matcher/adapters/source_freshness.py)
- [Application subprocess runner](../backend/jobs/job_runner.py)
- [Application progress validation and state projection](../backend/services/pipeline_progress.py)
- [Application run status](../backend/services/pipeline_status.py)
- [Overpass resource and rate-limit documentation](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)
- [GTFS format reference](https://gtfs.org/documentation/schedule/reference/)
