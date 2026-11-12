# Developer glossary

The terms of the code, the matching engine and the deployment. They add to the [glossary](0.4%20Glossary.md) of the user guide, which defines the words of the site, such as [match](0.4%20Glossary.md#match), [match type](0.4%20Glossary.md#match-type) and [OSM stop unit](0.4%20Glossary.md#osm-stop-unit).

## Stops in the code

### Namespace

A short name that identifies the source dataset or feed inside every key: `atlas` for the Swiss integration, or the value of `--namespace` for a GTFS feed. Equal raw identifiers from different namespaces never count as the same stop.

### Source stop

The engine's source-neutral name for a stop of the official dataset (an ATLAS platform or a GTFS stop), the `SourceStop` record. Its key is `<namespace>:<source_id>`, for example `atlas:ch:1:sloid:3000:501:33`. An [OSM element](0.4%20Glossary.md#osm-element)'s key names its type, for example `osm:node:123`. When it imports a bundle, the review application turns the `atlas:` keys back into SLOIDs.

### Representative

The member of a group that matching sees. In a [duplicate group](0.4%20Glossary.md#duplicate-group) it is the first platform by key; the others receive its matches by [propagation](0.4%20Glossary.md#propagation).

### Stop type

The kind of a map entry, `stop_type` in `stops_matched`: `matched`, `effectively_matched` (the middle of a two-sided stop, `ptv2_two_sided_stop` in the engine), `atlas_unmatched`, `osm_unmatched` or `osm_disused`. A [disused OSM element](0.4%20Glossary.md#disused-osm-element) is an `osm_disused` entry outside every stop unit and every stop count. See [A1](1.%20Database%20%26%20bundle%20import.md).

## Matching policy

### Dataset profile

The matching policy for one dataset, a `MatchingProfile` object in the engine. It decides:

- which OSM tags name a source stop exactly, for the [identifier rule](0.4%20Glossary.md#identifier-rule): `ref:sloid` and `railway:ref:sloid` for Switzerland,
- which other identifiers count as exact evidence ([reference rules](#reference-rule)),
- which [matching rules](0.4%20Glossary.md#matching-rule) run, and in which order,
- whether OSM elements are grouped into [stop units](0.4%20Glossary.md#osm-stop-unit), and with which distances,
- the distance limits of matching, the isolation radius and the thresholds that set [problem](0.4%20Glossary.md#problem) priorities.

The engine ships `profiles.SWITZERLAND` for ATLAS and uses the generic default profile for GTFS feeds. A profile is Python code inside the engine; it is unrelated to the review application's [review configuration](#review-configuration). See [E2 Matching process](../engine/documentation/2.%20Matching%20process.md#dataset-profiles).

### Reference rule

Part of a profile that allows one kind of source identifier to be compared with one OSM tag, for example ATLAS station numbers with `uic_ref`. Without a reference rule, equal strings are never treated as the same stop. See [E2.1 Reference matching](../engine/documentation/2.1%20Reference%20matching.md).

### Predicate

A [matching rule](0.4%20Glossary.md#matching-rule) in the code. The match type it decides is written as `method` in the bundle and copied into `stops_matched.match_type` by the importer, which never names one itself ([A1.1](1.1%20Bundle%20import%20and%20publication.md)).

## Engine architecture

### Matching engine

The `osm-public-transport-matcher` Python package and command-line tool, in its own repository. It reads sources, matches stops and routes, detects problems and writes a [result bundle](#result-bundle). It has no web or database dependency.

### Input integration

The dataset-specific part of the engine: acquisition, format adapters and the dataset profile for one dataset family. The Swiss integration is maintained in the engine; other datasets can use their own adapters. See [E1](../engine/documentation/1.%20Input%20integrations%20%26%20acquisition.md).

### Adapter

Code that parses one input format into normalized records, for example the ATLAS CSV reader or the OSM XML parser. The format readers (`adapters/atlas.py`, `adapters/gtfs.py`, `adapters/osm.py`) read explicit files and never download anything; downloading is [acquisition](#acquisition).

### Acquisition

The optional engine layer that downloads sources and caches prepared products in a [workspace](#workspace), reusing them while their checksums and the servers' validators still agree. See [E5.1 Source snapshot caching](../engine/documentation/5.1%20Source%20snapshot%20caching.md).

### Workspace

The engine's directory of downloaded and prepared inputs: `data/raw`, `data/processed`, `data/cache` and `data/source_metadata.json`.

### Result bundle

The engine's output and the contract between the two projects: one directory with `manifest.json` and nine compressed JSON Lines files. `schema_version` versions the format. See [Result bundle format](../engine/documentation/Result%20bundle%20format.md).

### Capability

A feature that a bundle supports, listed in its manifest: `stops`, `problems`, `routes` and `gtfs_identity`. The review application hides views that the active bundle does not support.

## Application and deployment

### Review application

This repository: the Flask website, PostGIS database, importer and scheduler that present a bundle for review. It never imports engine code. See [A3 Architecture](3.%20Application%20architecture%20%26%20deployment.md).

### Publication

The atomic switch that makes an imported bundle the visible [snapshot](0.4%20Glossary.md#snapshot): the import is built in a staging schema and published in one transaction, so readers see the previous snapshot until then. See [A1.1 Bundle import and publication](1.1%20Bundle%20import%20and%20publication.md).

### Run

One pipeline execution, identified by the bundle's `run_id`. Its mode is `full`, `match-import` or `import`; see [A3.3 Background scheduler](3.3%20Background%20scheduler.md).

### Review configuration

The JSON file named by `REVIEW_CONFIG`, such as `config/switzerland.json`: the website title, labels, map area and enabled views. It changes presentation only, never matching.
