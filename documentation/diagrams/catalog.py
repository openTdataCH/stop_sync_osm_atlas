"""Every documentation diagram, defined with the shared kit.

Each function returns a ``kit.Diagram``. ``DIAGRAMS`` maps an output name to
its documentation tree (``app`` or ``engine``) and builder. The rendered file
is ``<tree>/documentation/images/<name>.svg``.

Coordinates are in SVG user units on a canvas at most 960 wide, which the
portal scales to the article column. Keep text at 12 units or larger.
"""
from __future__ import annotations

from kit import (
    APP, ATLAS, CONTRACT, ENGINE, EXTERNAL, FAINT, GTFS, INK, MUTED, OSM, UNMATCHED,
    Diagram, Line, arrow, box, browser, chevron, code, divider, document, legend, node, note, pill, step,
    store, text, zone,
)


def overview_big_picture() -> Diagram:
    d = Diagram(
        960, 500,
        'How the project works',
        'Public sources enter the matching engine, a separate repository, through format adapters and a '
        'dataset profile. Its source-neutral core matches stops, compares routes and detects problems, then '
        'writes a versioned result bundle. The review application in this repository runs a pinned engine '
        'release on a schedule, imports each bundle and shows it on a website; other sites and scripts can '
        'use the same bundle. Reviewers use the findings to fix OpenStreetMap and report ATLAS issues.',
    )

    d.add(zone(20, 104, 160, 262, EXTERNAL, 'Sources'))
    for index, (title, line) in enumerate((
        ('ATLAS', 'Swiss stop registry'),
        ('Swiss GTFS', 'timetable'),
        ('Any GTFS feed', 'other datasets'),
        ('OpenStreetMap', 'XML extract'),
    )):
        d.add(box(32, 122 + index * 60, 136, 50, EXTERNAL, title, [line], title_size=13.5, line_size=12, gap=3,
                  pad=6))

    d.add(zone(202, 104, 372, 262, ENGINE, 'Matching engine', 'separate repository'))
    d.add(box(216, 128, 156, 128, ENGINE, 'Format adapters', [
        'ATLAS · GTFS · OSM', 'parse files into', 'common records', '+ your own adapter',
    ], title_size=14, line_size=12, gap=4, filled=False, pad=6))
    d.add(box(216, 270, 156, 80, ENGINE, 'Dataset profiles', ['Swiss · generic', 'rules, thresholds'],
              title_size=14, line_size=12, gap=4, filled=False, pad=6))
    d.add(box(398, 128, 162, 222, ENGINE, 'Source-neutral core', [
        'matches stops', 'compares routes', 'detects problems', '', 'no files, network', 'or database',
    ], title_size=14, line_size=12.5, gap=5, pad=4))
    for y in (147, 207, 267, 327):
        d.add(arrow([(168, y), (190, y), (190, 192), (214, 192)], corner=8))
    d.add(arrow([(372, 192), (396, 192)], color=ENGINE.stroke))
    d.add(arrow([(372, 310), (396, 310)], color=ENGINE.stroke))

    d.add(document(594, 174, 132, 126, CONTRACT, 'Result bundle', [
        'versioned files', 'stops, routes,', 'problems',
    ], align='center', title_size=13.5, line_size=11.5))
    d.add(arrow([(560, 237), (592, 237)], color=CONTRACT.stroke))

    d.add(box(752, 112, 188, 52, EXTERNAL, 'Other sites', ['other datasets or countries'],
              title_size=13.5, line_size=12, gap=3, dashed=True, filled=False))
    d.add(box(752, 176, 188, 42, EXTERNAL, 'Scripts and research', [],
              title_size=13.5, dashed=True, filled=False))
    d.add(box(752, 238, 188, 120, APP, 'Review application', [
        code('stop_sync_osm_atlas', size=12), 'this repository', 'Flask, PostGIS, map UI',
        'imports each bundle',
    ], title_size=14, line_size=12, gap=4, pad=6))
    for y in (138, 197, 298):
        d.add(arrow([(726, 237), (738, 237), (738, y), (750, y)], corner=5))

    d.add(arrow([(800, 358), (800, 400), (479, 400), (479, 368)], kind='invoke', color=APP.stroke,
                label='runs a pinned engine release on a schedule', label_at=(640, 400), label_tone=APP))
    d.add(arrow([(900, 358), (900, 432), (100, 432), (100, 368)], kind='optional', color=INK,
                label='reviewers fix OpenStreetMap and report ATLAS data issues', label_at=(318, 432)))

    legend_svg, width = legend(32, 474, [
        ('flow', MUTED, 'data flow'),
        ('invoke', APP.stroke, 'starts or calls'),
        ('optional', INK, 'people act on the findings'),
    ])
    d.add(legend_svg)
    d.add(note(32 + width + 28, 468, ['Dashed boxes: possible further uses of the bundle.'], size=12, color=MUTED))
    return d


def architecture_system() -> Diagram:
    d = Diagram(
        960, 700,
        'System architecture',
        'The review application\'s pipeline runner starts the separately installed matching engine as a '
        'command-line process and reads its progress events. The engine downloads or reuses public sources '
        'in its workspace, matches them and writes a result bundle. The runner then imports the bundle: it '
        'validates it, loads a private staging schema and switches the public PostGIS tables. The Flask web '
        'application serves pages and a JSON API from the published snapshot and reads runtime status files.',
    )

    # Sources feed the engine only.
    d.add(box(24, 92, 320, 74, EXTERNAL, 'Public sources', [
        'ATLAS · GTFS · OpenStreetMap (Overpass) ·', 'Swiss boundary GeoJSON',
    ], title_size=14, line_size=12.5))

    d.add(zone(24, 200, 320, 426, ENGINE, 'Matching engine', 'separate repository'))
    d.add(box(44, 228, 280, 62, ENGINE, 'Acquisition (optional)', ['freshness checks, downloads, caches'],
              line_size=12.5))
    d.add(store(44, 310, 280, 82, ENGINE, 'Engine workspace', [
        code('data/raw · data/processed', size=12), code('data/cache', size=12),
    ]))
    d.add(box(44, 412, 280, 102, ENGINE, 'Matching', [
        'adapters normalize the inputs; the', 'dataset profile configures the core;',
        'stops are matched, problems found,', 'routes compared',
    ], line_size=12.5, gap=4))
    d.add(box(44, 534, 280, 70, ENGINE, 'Bundle writer', ['validates, then publishes a', 'new run directory'],
              line_size=12.5, gap=4))
    for top, bottom in ((166, 226), (290, 308), (392, 410), (514, 532)):
        d.add(arrow([(184, top), (184, bottom)]))

    d.add(zone(560, 200, 376, 426, APP, 'Review application', 'this repository'))
    d.add(box(578, 228, 160, 92, APP, 'Pipeline runner', [code('backend/jobs', size=12), 'schedule, run lease,', 'status updates'],
              title_size=14, line_size=12.5, gap=4))
    d.add(store(606, 374, 132, 80, APP, 'Runtime state', [code('data/runtime', size=12)], title_size=13.5))
    d.add(box(578, 520, 160, 90, APP, 'Importer', [code('backend/importing', size=12), 'validate, project,', 'stage, switch'],
              title_size=14, line_size=12.5, gap=4))
    d.add(browser(760, 228, 160, 92, APP, 'Browser', ['map, problems,', 'routes, data, docs']))
    d.add(box(760, 382, 160, 78, APP, 'Web app', [code('backend/blueprints', size=11.5), 'pages and JSON API'],
              title_size=14, line_size=12, gap=4))
    d.add(store(760, 520, 160, 90, APP, 'PostGIS', ['published', 'snapshot tables']))

    # Across the boundary.
    d.add(arrow([(578, 252), (346, 252)], kind='invoke', color=APP.stroke))
    d.add(text(452, 240, 'runs the CLI', size=12, color=APP.text, anchor='middle'))
    d.add(arrow([(346, 290), (576, 290)], color=ENGINE.stroke))
    d.add(text(452, 308, 'progress events', size=12, color=ENGINE.text, anchor='middle'))
    d.add(document(366, 524, 172, 84, CONTRACT, 'Result bundle', [code('data/results/<run>/', size=11.5), 'manifest + 9 files'],
                   align='center', title_size=14, line_size=12))
    d.add(arrow([(324, 566), (364, 566)], color=CONTRACT.stroke))
    d.add(arrow([(538, 566), (576, 566)], color=CONTRACT.stroke))

    # Inside the application.
    d.add(arrow([(592, 320), (592, 518)], kind='invoke', color=APP.stroke))
    d.add(text(598, 478, 'then', size=12, color=APP.text))
    d.add(text(598, 493, 'imports', size=12, color=APP.text))
    d.add(arrow([(672, 320), (672, 372)], color=MUTED))
    d.add(arrow([(738, 418), (758, 418)], color=MUTED))
    d.add(arrow([(738, 566), (758, 566)], color=MUTED))
    d.add(arrow([(840, 520), (840, 462)], color=MUTED))
    d.add(arrow([(840, 382), (840, 322)], color=MUTED))

    for number, (x, y) in enumerate(((560, 252), (44, 228), (44, 412), (324, 566), (578, 520),
                                     (760, 520), (840, 352), (606, 374)), start=1):
        d.add(step(x, y, number))

    legend_svg, _ = legend(24, 666, [
        ('zone', ENGINE, 'engine'), ('zone', APP, 'review application'), ('box', CONTRACT, 'shared contract'),
        ('flow', MUTED, 'data flow'), ('invoke', APP.stroke, 'starts or calls'),
    ])
    d.add(legend_svg)
    return d


def architecture_deployment() -> Diagram:
    d = Diagram(
        960, 700,
        'Deployment with Docker Compose',
        'Docker Compose runs the app, scheduler, db and one-shot migrator services. The app container serves '
        'the website on port 5001 and reads the database. The scheduler container runs the pipeline runner, '
        'which starts the installed public-transport-matcher CLI as a subprocess, then imports the bundle in the same '
        'process and switches the database snapshot. The db container runs PostgreSQL with PostGIS on the '
        'postgres_data volume; the migrator upgrades its schema before the other services start. The host '
        'folder ./data is mounted into every application container and holds the engine workspace, result '
        'bundles, runtime state and analytics files.',
    )

    d.add(browser(48, 88, 220, 58, EXTERNAL, "Reviewers' browsers"))
    d.add(box(632, 88, 280, 58, EXTERNAL, 'Public sources', ['opentransportdata.swiss · Overpass'],
              title_size=14, line_size=12.5, gap=3))

    d.add(zone(24, 176, 912, 474, EXTERNAL, 'Docker Compose project', 'docker-compose.yml', tab_x=300))
    d.add(box(48, 206, 220, 108, APP, 'app', ['Flask pages and JSON API', 'port 5001', code('target: app-stage', size=12)],
              gap=5))
    d.add(box(48, 334, 176, 64, APP, 'migrator (one-shot)', ['upgrades the db schema'], title_size=13.5,
              line_size=12.5, gap=4, dashed=True))

    d.add(box(310, 206, 240, 196, EXTERNAL, 'db', ['PostgreSQL 16 + PostGIS 3.4', 'port 5432'],
              valign='top', gap=5))
    d.add(store(334, 284, 192, 100, EXTERNAL, code('postgres_data', size=13), ['named volume:', 'the app database'],
                title_size=13, line_size=12.5))

    d.add(box(592, 206, 320, 196, APP, 'scheduler', [code('target: scheduler-stage', size=12)], valign='top', gap=4))
    d.add(box(608, 260, 288, 44, APP, None, [code('python -m backend.jobs.service', size=12),
                                             'APScheduler and pipeline runner'], line_size=12, gap=3, pad=6))
    d.add(box(606, 324, 200, 62, ENGINE, code('public-transport-matcher', size=11.5), ['CLI subprocess'],
              title_size=11.5, line_size=12, gap=4, pad=6))
    d.add(box(814, 324, 82, 62, APP, 'Importer', ['in-process'], title_size=13, line_size=12, gap=4, pad=4))
    d.add(arrow([(706, 304), (706, 322)], kind='invoke', color=APP.stroke))
    d.add(arrow([(855, 304), (855, 322)], kind='invoke', color=APP.stroke))

    d.add(store(48, 436, 864, 196, APP, code('./data', size=14), ['host folder, mounted at /app/data in every application container'],
                valign='top', line_size=12.5))
    for x, tone, title, lines in (
        (96, ENGINE, 'Workspace', [code('raw/ processed/', size=11.5), code('cache/', size=11.5), 'source metadata']),
        (306, CONTRACT, 'Result bundles', [code('results/<run>/', size=11.5), 'one directory', 'per run']),
        (516, APP, 'Runtime state', [code('runtime/', size=11.5), 'status, run lease,', 'export tasks']),
        (726, APP, 'Analytics', [code('stats.json', size=11.5), code('data_meta.json', size=11.5)]),
    ):
        d.add(document(x, 512, 138, 100, tone, title, lines, title_size=13, line_size=12, gap=4))

    d.add(arrow([(158, 146), (158, 204)]))
    d.add(text(166, 165, 'HTTP :5001', size=12, color=MUTED))
    d.add(arrow([(820, 148), (820, 206)], color=ENGINE.stroke))
    d.add(text(828, 165, 'downloads', size=12, color=ENGINE.text))
    d.add(arrow([(268, 250), (308, 250)], color=MUTED))
    d.add(text(288, 240, 'SQL', size=12, color=MUTED, anchor='middle'))
    d.add(arrow([(592, 250), (552, 250)], color=MUTED))
    d.add(text(572, 240, 'SQL', size=12, color=MUTED, anchor='middle'))
    d.add(arrow([(246, 316), (246, 434)], start_head=True, color=MUTED))
    d.add(arrow([(752, 402), (752, 434)], start_head=True, color=MUTED))

    legend_svg, _ = legend(48, 676, [
        ('box', APP, 'review application'), ('box', ENGINE, 'engine (installed package)'),
        ('box', EXTERNAL, 'third-party image or service'), ('flow', MUTED, 'reads or writes'),
        ('invoke', APP.stroke, 'starts or calls'),
    ])
    d.add(legend_svg)
    return d


def overview_one_stop() -> Diagram:
    d = Diagram(
        960, 560,
        'One stop in three datasets',
        'An illustrative stop with two platforms. In OpenStreetMap each platform is a pair of nodes: a '
        'platform node and a stop position on the road. ATLAS has one record per platform, identified by a '
        'SLOID and sharing the station UIC number. GTFS has one stop per platform; in the current Swiss feed '
        'its stop_id is the SLOID. The project groups OSM nodes into stop units (1), links ATLAS platforms to '
        'OSM stops (2), maps GTFS stop_ids to SLOIDs (3) and pairs GTFS routes with OSM route relations (4).',
    )

    d.add(zone(24, 104, 912, 118, OSM, 'OpenStreetMap'))
    d.add(zone(24, 270, 912, 92, ATLAS, 'ATLAS'))
    d.add(zone(24, 410, 912, 92, GTFS, 'GTFS timetable'))

    for center, (platform_id, position_id, local_ref) in ((240, ('101', '102', '1')), (470, ('103', '104', '2'))):
        d.add(arrow([(center - 40, 146), (center + 40, 146)], end_head=False, color=OSM.stroke, width=2.2,
                    kind='invoke'))
        d.add(node(center - 40, 146, OSM, radius=11, letter='P'))
        d.add(node(center + 40, 146, OSM, radius=11, letter='S', hollow=True))
        d.add(text(center - 40, 176, f'node {platform_id}', size=11.5, color=INK, anchor='middle'))
        d.add(text(center + 40, 176, f'node {position_id}', size=11.5, color=INK, anchor='middle'))
        d.add(text(center, 200, f'uic_ref=8591234 · local_ref={local_ref}', size=10.5, color=OSM.text,
                   anchor='middle', mono=True))
        d.add(box(center - 95, 288, 190, 60, ATLAS, f'Platform {local_ref}', [
            code(f'ch:1:sloid:91234:0:{local_ref}', size=12), f'UIC 8591234 · designation {local_ref}',
        ], title_size=13.5, line_size=12, gap=3, pad=6))
        d.add(box(center - 95, 428, 190, 60, GTFS, 'Stop', [
            code(f'ch:1:sloid:91234:0:{local_ref}', size=12), 'served by route 31',
        ], title_size=13.5, line_size=12, gap=3, pad=6))
        d.add(arrow([(center, 286), (center, 210)], end_head=False, color=ATLAS.stroke, width=2.2))
        d.add(arrow([(center, 426), (center, 350)], end_head=False, color=GTFS.stroke, width=2.2))

    d.add(box(690, 122, 220, 82, OSM, 'Route relation', [code('route=bus · ref=31', size=12), 'ordered stops and platforms'],
              title_size=13.5, line_size=12, gap=4))
    d.add(box(690, 428, 220, 60, GTFS, 'Route 31', ['trips, grouped into itineraries'], title_size=13.5,
              line_size=12, gap=4))
    d.add(arrow([(800, 426), (800, 206)], end_head=False, color=MUTED, width=2.2))
    d.add(note(812, 300, ['ATLAS has no route', 'records: routes are', 'rebuilt from GTFS'], size=11.5))

    for number, (x, y) in ((1, (240, 128)), (2, (240, 246)), (3, (240, 388)), (4, (800, 388))):
        d.add(step(x, y, number))

    legend_svg, _ = legend(24, 536, [
        ('node:P', OSM, 'platform'), ('hollow:S', OSM, 'stop position'), ('link-dashed', OSM.stroke, '1 OSM stop unit'),
        ('link', ATLAS.stroke, '2 stop match'), ('link', GTFS.stroke, '3 identity'),
        ('link', MUTED, '4 route match'),
    ], column_gap=22)
    d.add(legend_svg)
    return d


def engine_anatomy() -> Diagram:
    d = Diagram(
        960, 520,
        'Inside the matching engine',
        'The engine has three parts. Input integrations are dataset-specific: optional acquisition downloads '
        'files, format adapters parse them into normalized records, and dataset profiles hold the matching '
        'policy. The source-neutral core matches stops, detects problems, compares routes and computes quality '
        'metrics without any file, network or database access. Result production validates the complete result '
        'and atomically publishes the bundle.',
    )

    d.add(zone(24, 104, 300, 362, ENGINE, 'Input integrations', dashed=True))
    d.add(box(44, 130, 260, 70, ENGINE, 'Dataset profile', [code('profiles/switzerland.py', size=11.5),
                                                          'rules, order, thresholds'],
              title_size=14, line_size=12.5, gap=4, filled=False))
    d.add(box(44, 222, 260, 96, ENGINE, 'Format adapters', [
        code('adapters/atlas.py · gtfs.py', size=11.5), code('adapters/osm.py · osm_routes.py', size=11.5),
        'parse files into records',
    ], title_size=14, line_size=12.5, gap=4, filled=False))
    d.add(box(44, 340, 260, 96, ENGINE, 'Acquisition (optional)', [
        code('acquisition/overpass.py', size=11.5), code('adapters/acquisition.py', size=11.5),
        'downloads, freshness, caches',
    ], title_size=14, line_size=12.5, gap=4, filled=False, dashed=True))
    d.add(arrow([(174, 340), (174, 320)]))
    d.add(text(182, 334, 'files', size=11.5, color=MUTED))

    d.add(zone(356, 104, 288, 362, ENGINE, 'Source-neutral core', 'no I/O'))
    d.add(box(374, 130, 252, 152, ENGINE, 'Stop matching', [
        code('api.match()', size=12), '1  group OSM nodes into units', '2  run the matching rules in order',
        '3  detect stop problems',
    ], title_size=14, line_size=12.5, gap=6, align='start', pad=14))
    d.add(box(374, 304, 252, 62, ENGINE, 'Route comparison', [code('routes.py', size=12)], title_size=14, gap=4))
    d.add(box(374, 386, 252, 50, ENGINE, 'Quality metrics', [code('statistics.py', size=12)], title_size=13.5,
              line_size=12, gap=3, pad=6))
    d.add(arrow([(500, 282), (500, 302)]))

    d.add(arrow([(304, 165), (372, 165)], color=ENGINE.stroke))
    d.add(arrow([(304, 262), (372, 262)], color=ENGINE.stroke))

    d.add(zone(676, 104, 260, 362, ENGINE, 'Result production'))
    d.add(box(696, 130, 220, 100, ENGINE, 'Bundle writer', [code('results/bundle.py', size=12),
                                                        'validates the result, writes', 'checksums, renames atomically'],
              title_size=14, line_size=12.5, gap=4))
    d.add(document(726, 262, 160, 104, CONTRACT, 'Result bundle', [code('manifest.json', size=11.5), '+ 9 record files'],
                   align='center', title_size=14, line_size=12))
    d.add(arrow([(806, 230), (806, 260)], color=CONTRACT.stroke))
    d.add(arrow([(644, 180), (694, 180)], color=ENGINE.stroke))

    d.add(note(44, 486, ['Reads files and, for acquisition,', 'the network. Policy lives in profiles.'], size=11.5))
    d.add(note(374, 486, ['Receives records and a profile;', 'never opens files or connections.'], size=11.5))
    d.add(note(696, 486, ['The only code that creates', 'a bundle directory.'], size=11.5))
    return d


MATCHING_RULES = (
    ('trio', 'two platforms ↔ the two sides of an OSM trio', 'distance_matching_trio'),
    ('exact', 'same reference value, where the profile allows it', 'exact'),
    ('name', 'same name; platform code = local_ref breaks ties', 'name'),
    ('route', '≤ 50 m, shared route and direction, mutual best', 'route_gtfs_*'),
    ('group_proximity', '≤ 50 m, best conflict-free assignment per group', 'distance_matching_1_*'),
    ('long_distance_group_proximity', 'the same assignment, up to 150 m', 'long_distance_group_proximity_*'),
    ('local_ref', '≤ 50 m and platform code = local_ref; closest', 'distance_matching_2'),
    ('nearest_single', 'exactly one compatible candidate ≤ 50 m', 'distance_matching_3a'),
    ('nearest_ratio', 'nearest is ≥ 4× closer than the second', 'distance_matching_3b'),
    ('nearest_second', 'exactly one candidate again, after rule 9', 'distance_matching_3a_second_pass'),
)


def matching_rule_ladder() -> Diagram:
    rows = len(MATCHING_RULES)
    top, pitch = 150, 44
    height = top + rows * pitch + 120
    d = Diagram(
        960, height,
        'The matching rules, in order',
        'Before the rules run, OSM nodes are grouped into pairs and trios. Ten rule executions then run in a '
        'fixed order: trio, exact reference, name, route, group proximity at 50 m and 150 m, local reference, '
        'single nearest candidate, ratio test and a second single-candidate pass. Each rule only sees source '
        'stops that are still unmatched, and every accepted pair is committed immediately, which locks both '
        'sides. Stops left at the end are unmatched and go to problem detection.',
    )

    d.add(arrow([(32, 112), (32, top + rows * pitch + 22)], color=INK, width=2.5, end_head=True))
    d.add(box(60, 92, 600, 38, EXTERNAL, None, ['Before the rules: group OSM nodes into pairs and trios (profile grouping policy)'],
              line_size=12.5, pad=8, dashed=True))
    d.add(text(684, 116, 'match type recorded', size=12, bold=True, color=MUTED))

    for index, (rule, description, match_type) in enumerate(MATCHING_RULES):
        y = top + index * pitch
        d.add(box(60, y, 600, 36, ENGINE, None, [], radius=8))
        d.add(text(76, y + 23, rule, size=12, bold=True, color=ENGINE.text, mono=True, max_width=236))
        d.add(text(320, y + 23, description, size=12.5, color=INK, max_width=330))
        d.add(arrow([(660, y + 18), (680, y + 18)], color=MUTED, width=1.5))
        tag, _ = pill(684, y + 18, code(match_type, size=11), ENGINE, size=11)
        d.add(tag)
        d.add(step(32, y + 18, index + 1))

    end = top + rows * pitch + 30
    d.add(box(60, end, 600, 44, UNMATCHED, None, [
        'Still unmatched at the end: isolation is measured and unmatched problems are detected',
    ], line_size=12.5, pad=8))
    d.add(note(684, end + 6, ['Every accepted pair goes through', 'ctx.commit(), which also matches', 'duplicate siblings and pair partners.'],
               size=11.5))
    return d


BUNDLE_SECTIONS = (
    ('Entities', (
        ('source_stops', ['one row per source stop:', 'key, namespace, position,', 'name, references']),
        ('osm_nodes', ['one row per OSM element:', 'key, element type, position,', 'tags']),
        ('groups', ['source duplicate groups;', 'OSM stop units: single,', 'pair or trio']),
    )),
    ('Decisions', (
        ('matches', ['one row per link:', 'source key, OSM key,', 'method, distance, evidence']),
        ('unmatched', ['every entity without a link,', 'with its isolated and', 'effectively_matched flags']),
        ('problems', ['stable id, type, priority', '1–3, affected keys,', 'evidence']),
    )),
    ('Details', (
        ('routes', ['families, itineraries, stop', 'calls and their matches']),
        ('extensions', ['route evidence, quality', 'metrics, Swiss identity data']),
        ('diagnostics', ['machine-readable notes, e.g.', 'missing route evidence']),
    )),
)


def result_bundle_anatomy() -> Diagram:
    d = Diagram(
        960, 560,
        'Anatomy of a result bundle',
        'A result bundle is a directory with manifest.json and nine gzip-compressed JSON Lines files. The '
        'manifest records the schema version, engine version, run id, profile and metadata, and the row count, '
        'size and SHA-256 checksum of every file. The files hold entities (source stops, OSM nodes, groups), '
        'decisions (matches, unmatched entities, problems) and details (routes, extensions, diagnostics). Rows '
        'refer to entities by their keys.',
    )

    d.add(document(24, 140, 262, 282, CONTRACT, code('manifest.json', size=14), [
        Line('schema_version: 1', 12.5, mono=True), Line('engine_version', 12.5, mono=True),
        Line('run_id, generated_at', 12.5, mono=True), Line('profile_id', 12.5, mono=True),
        Line('metadata', 12.5, mono=True), 'capabilities, inputs, profile,', 'summary',
        Line('files', 12.5, mono=True), 'name, rows, bytes and', 'sha256 of each section',
    ], title_size=14, line_size=12.5, gap=7))
    d.add(arrow([(288, 281), (318, 281)], color=CONTRACT.stroke))

    columns = (326, 530, 734)
    for row, (label, sections) in enumerate(BUNDLE_SECTIONS):
        top = 118 + row * 122
        d.add(text(326, top - 8, label.upper(), size=11.5, bold=True, color=MUTED, letter_spacing=1.2))
        for column, (name, lines) in zip(columns, sections):
            d.add(document(column, top, 196, 92, CONTRACT, code(name, size=13), lines,
                           title_size=13, line_size=12, gap=4))

    d.add(arrow([(424, 362 - 122), (424, 212)], color=MUTED, start_head=False))
    d.add(arrow([(472, 240), (472, 226), (628, 226), (628, 212)], color=MUTED, corner=6))
    d.add(text(432, 230, 'keys', size=11.5, color=MUTED))

    d.add(note(326, 478, [
        'Each section is a file named <section>.jsonl.gz: one JSON object per line.',
        'Rows refer to entities by key: <namespace>:<id> for sources, such as atlas:<SLOID>,',
        'and osm:<type>:<id> for OSM elements, such as osm:node:<id>.',
        'Every entity appears either in matches or in unmatched, never in both.',
    ], size=12, gap=6))
    return d


def import_snapshot_publication() -> Diagram:
    d = Diagram(
        960, 470,
        'Importing and publishing a snapshot',
        'The importer validates the bundle without database access, projects it onto application rows, creates '
        'a private staging schema with the table constraints, loads the rows with COPY and builds indexes. '
        'Readers keep using the published run during all of this. One short transaction then moves the old '
        'tables out of the public schema and the staged tables in, and records the new run. If anything fails '
        'before that commit, the staging schema is dropped and the previous run stays published.',
    )

    steps = (
        ('Validate', [code('database.validate', size=12), 'schema, checksums,', 'row counts, keys']),
        ('Prepare rows', [code('database.prepare', size=12), 'app rows, geometry,', 'route overlaps']),
        ('Stage', [code('database.load', size=12), 'private schema with', 'PK, unique and FK']),
        ('Load and index', [code('database.load', size=12), 'COPY rows, then', 'indexes, ANALYZE']),
        ('Switch', [code('publish.swap', size=12), 'old tables out,', 'staged tables in']),
    )
    xs = [30 + index * 184 for index in range(len(steps))]
    for index, (x, (title, lines)) in enumerate(zip(xs, steps)):
        d.add(box(x, 100, 164, 96, APP, title, lines, title_size=14, line_size=12.5, gap=4,
                  filled=index == 4, stroke_width=2.2 if index == 4 else 1.5))
        d.add(step(x, 100, index + 1))
        if index < len(steps) - 1:
            d.add(arrow([(x + 164, 148), (x + 182, 148)], color=APP.stroke))
    d.add(note(30, 212, ['No database access yet.'], size=11.5))
    d.add(note(398, 212, ['Readers see none of this.'], size=11.5))

    commit_x = 880
    d.add(text(30, 262, 'PUBLIC SCHEMA', size=11.5, bold=True, color=MUTED, letter_spacing=1.2))
    d.add(text(30, 278, 'what readers see', size=11.5, color=MUTED))
    d.add(box(170, 248, commit_x - 170, 40, EXTERNAL, None, ['run N: the previously published snapshot'],
              line_size=12.5, pad=6, radius=6))
    d.add(box(commit_x, 248, 930 - commit_x, 40, APP, None, ['N+1'], line_size=12.5, pad=4, radius=6))

    d.add(text(30, 334, 'STAGING SCHEMA', size=11.5, bold=True, color=MUTED, letter_spacing=1.2))
    d.add(text(30, 350, code('import_<token>', size=11.5), size=11.5, color=MUTED))
    d.add(box(398, 320, commit_x - 398, 40, APP, None, ['run N+1 is created, loaded and indexed here'],
              line_size=12.5, pad=6, radius=6, dashed=True, filled=False))

    d.add(arrow([(commit_x, 222), (commit_x, 392)], kind='invoke', color=INK, end_head=False, width=1.6))
    d.add(text(commit_x, 410, 'commit', size=12, bold=True, color=INK, anchor='middle'))
    d.add(note(30, 432, [
        'The switch waits at most 3 s for table locks and may run 25 s. A failure before the commit drops the staging',
        'schema and leaves run N published. After the commit the old tables are dropped and analytics regenerated.',
    ], size=12, gap=4))
    return d


def route_model() -> Diagram:
    d = Diagram(
        960, 620,
        'The route model',
        'Both sides are normalized into the same three levels: a line family, its itineraries (one per '
        'direction or variant) and each itinerary\'s ordered stop calls. On the ATLAS side these are rebuilt '
        'from GTFS; on the OSM side they come from route_master and route relations. Families are matched '
        'first, by GTFS route id. Itineraries are paired only inside a matched family: their directions must '
        'agree and at least 80 percent of the longer stop list must be shared in order. In the example, four '
        'of five stops align, which is exactly 80 percent.',
    )

    d.add(zone(24, 104, 360, 380, ATLAS, 'ATLAS side', 'rebuilt from GTFS'))
    d.add(zone(576, 104, 360, 380, OSM, 'OSM side', 'PTv2 relations'))

    d.add(box(44, 130, 320, 58, ATLAS, 'Line family', [code('GTFS route_id 31-B-j26-1', size=11.5)],
              title_size=14, gap=4))
    d.add(box(596, 130, 320, 58, OSM, 'Line family', [code('route_master ref=31', size=11.5)],
              title_size=14, gap=4))
    for x, tone, title, lines, strong in (
        (44, ATLAS, 'Itinerary', ['direction 1', '→ Bahnhof'], False),
        (212, ATLAS, 'Itinerary', ['direction 0', '→ Spital'], True),
        (596, OSM, 'Route relation', ['direction 0', '→ Spital'], True),
        (764, OSM, 'Route relation', ['direction 1', '→ Bahnhof'], False),
    ):
        d.add(box(x, 216, 152, 72, tone, title, lines, title_size=13.5, line_size=12.5, gap=4,
                  stroke_width=2.4 if strong else 1.5, filled=strong))
    for family_x, children in ((204, (120, 288)), (756, (672, 840))):
        for child in children:
            d.add(arrow([(family_x, 188), (family_x, 202), (child, 202), (child, 214)], end_head=False,
                        color=FAINT, corner=6))

    atlas_stops = ('A Seeplatz', 'B Post', 'C Schule', 'D Markt', 'E Spital')
    osm_stops = ('A Seeplatz', 'B Post', 'X Kirche', 'D Markt', 'E Spital')
    first, pitch = 334, 30
    d.add(arrow([(288, 288), (288, first - 14)], end_head=False, color=ATLAS.stroke, width=1.5))
    d.add(arrow([(672, 288), (672, first - 14)], end_head=False, color=OSM.stroke, width=1.5))
    d.add(arrow([(288, first), (288, first + 4 * pitch)], end_head=False, color=ATLAS.stroke, width=3))
    d.add(arrow([(672, first), (672, first + 4 * pitch)], end_head=False, color=OSM.stroke, width=3))
    for index, (atlas_stop, osm_stop) in enumerate(zip(atlas_stops, osm_stops)):
        y = first + index * pitch
        shared = atlas_stop == osm_stop
        if shared:
            d.add(arrow([(298, y), (662, y)], kind='optional', color=MUTED, end_head=False, width=1.5))
        d.add(node(288, y, ATLAS, radius=8, hollow=not shared))
        d.add(node(672, y, OSM, radius=8, hollow=not shared))
        d.add(text(274, y + 4.5, atlas_stop, size=12.5, anchor='end', color=INK if shared else MUTED))
        d.add(text(686, y + 4.5, osm_stop, size=12.5, color=INK if shared else MUTED))
    d.add(note(44, first - 8, ['Stop calls,', 'in order'], size=11.5))
    d.add(note(916, first - 8, ['Stop calls,', 'in order'], size=11.5, anchor='end'))

    tag, _ = pill(480, 159, 'family match', EXTERNAL, anchor='middle', filled=False)
    d.add(arrow([(364, 159), (596, 159)], color=INK, end_head=False, width=2), tag)
    tag, _ = pill(480, 252, 'itinerary match', EXTERNAL, anchor='middle', filled=False)
    d.add(arrow([(364, 252), (596, 252)], color=INK, end_head=False, width=2), tag)
    d.add(step(390, 159, 1))
    d.add(step(390, 252, 2))
    d.add(text(480, 478, '4 of 5 stops in order: 80%', size=12.5, bold=True, color=INK, anchor='middle'))

    for number, top, lines in (
        (1, 512, ['Families match by GTFS route id: exact (score 1.0), with the year code normalized to -jXX (0.95),',
                  'or by display id (0.9). Each family appears in at most one match.']),
        (2, 554, ['Itineraries pair only inside a matched family: same direction, and at least 80% of the longer',
                  'stop list shared in order. Stop calls are the same stop when their resolved SLOIDs or, failing',
                  'that, UIC numbers agree.']),
    ):
        d.add(step(34, top + 6, number, radius=10))
        d.add(note(54, top, lines, size=12, gap=5))
    return d


PIPELINE_PHASES = (
    (('Check', 'sources'), ENGINE), (('Prepare', 'source files'), ENGINE), (('Load', 'matching', 'inputs'), ENGINE),
    (('Stop', 'matching'), ENGINE), (('Route', 'matching'), ENGINE), (('Build', 'result', 'bundle'), ENGINE),
    (('Stage', 'database'), APP), (('Publish', 'dataset'), APP),
)
PIPELINE_MODES = (
    ('full', 'every phase', 'RRRRRRRR'),
    ('match-import', 'existing source files', 'SURRRRRR'),
    ('import', 'an existing bundle', 'SSSSSURR'),
)


def pipeline_phases_and_modes() -> Diagram:
    d = Diagram(
        960, 400,
        'Pipeline phases and run modes',
        'A pipeline run has eight phases. The engine performs the first six: check sources, prepare source files, '
        'load matching inputs, stop matching, route matching and building the result bundle. The review '
        'application performs the last two: staging the database and publishing the dataset. Mode full runs '
        'every phase. Mode match-import skips the source check and reuses the existing source files. Mode '
        'import skips everything up to the bundle, reuses an existing bundle and only stages and publishes it.',
    )

    left, width, tip = 166, 102, 14
    xs = [left + index * (width - tip / 2) for index in range(len(PIPELINE_PHASES))]
    for index, (x, (lines, tone)) in enumerate(zip(xs, PIPELINE_PHASES)):
        d.add(chevron(x, 100, width, 52, tone, lines, tip=tip, first=index == 0, size=11))
    engine_end = xs[5] + width - tip / 2
    d.add(divider(xs[0], 168, engine_end - 6, 168, color=ENGINE.stroke, dash=None, width=2))
    d.add(text((xs[0] + engine_end) / 2, 186, 'engine: public-transport-matcher CLI', size=12, bold=True,
               color=ENGINE.text, anchor='middle'))
    d.add(divider(xs[6] + 6, 168, xs[7] + width, 168, color=APP.stroke, dash=None, width=2))
    d.add(text((xs[6] + xs[7] + width) / 2, 186, 'application: importer', size=12, bold=True,
               color=APP.text, anchor='middle'))

    for row, (mode, summary, pattern) in enumerate(PIPELINE_MODES):
        y = 232 + row * 46
        d.add(text(24, y + 4, code(mode, size=13), size=13, bold=True, color=INK))
        d.add(text(24, y + 21, summary, size=11, color=MUTED, max_width=140))
        for index, (x, state) in enumerate(zip(xs, pattern)):
            center = x + (width - tip) / 2 + (0 if index == 0 else tip / 2)
            # Filled: the phase runs. Outlined in its owner's colour: reused. Grey: skipped.
            tone = PIPELINE_PHASES[index][1] if state != 'S' else EXTERNAL
            label = {'R': 'runs', 'U': 'reused', 'S': 'skipped'}[state]
            tag, _ = pill(center, y + 6, label, tone, anchor='middle', size=11.5, filled=state == 'R')
            d.add(tag)
    d.add(note(168, 368, ['Within a running phase, cached work is shown as reused, stage by stage (see the progress contract).'],
               size=11.5))
    return d


DIAGRAMS = (
    ('overview-big-picture', 'app', overview_big_picture),
    ('overview-one-stop', 'app', overview_one_stop),
    ('architecture-system', 'app', architecture_system),
    ('architecture-deployment', 'app', architecture_deployment),
    ('engine-anatomy', 'engine', engine_anatomy),
    ('matching-rule-ladder', 'engine', matching_rule_ladder),
    ('result-bundle-anatomy', 'engine', result_bundle_anatomy),
    ('import-snapshot-publication', 'app', import_snapshot_publication),
    ('route-model', 'engine', route_model),
    ('pipeline-phases-and-modes', 'app', pipeline_phases_and_modes),
)
