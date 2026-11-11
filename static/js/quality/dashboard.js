/**
 * Code quality dashboard: the code map of both repositories at three depths, with the CI results of the running commit.
 *
 * The three levels are one picture. A module is a circle, at the same place on Modules and Files: filled on Modules,
 * holding its files as dots on Files. On Functions every function and class is a dot in its module's circle. A module
 * sits above the modules it declares as dependencies, so a declared dependency arcs downwards on the outer side of its
 * column, and an arc on the inner side goes upwards, against the declared layering.
 */
(function (global) {
    'use strict';

    // Canvas styles cannot read CSS variables: these are the palette values of tokens.css.
    const NAVY = '#174092';
    const GREEN = '#4caf50';
    const PURPLE = '#6b21a8';
    const INK = '#111111';
    const MUTED = '#6c757d';
    const FONT = '"Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif';

    /** ``color`` at ``share`` of full strength over white: a lighter shade without a new palette colour. */
    function tint(color, share) {
        const channel = (offset) => Math.round(parseInt(color.slice(offset, offset + 2), 16) * share + 255 * (1 - share));
        return '#' + [1, 3, 5].map((offset) => channel(offset).toString(16).padStart(2, '0')).join('');
    }

    const CRITICALITY = {
        critical: { color: NAVY, meaning: 'A defect can publish wrong, incomplete or lost data, or block recovery or deployment.' },
        high: { color: tint(NAVY, 0.68), meaning: 'A defect shows wrong results or stops data from refreshing, while the published data stays recoverable.' },
        medium: { color: tint(NAVY, 0.42), meaning: 'A defect degrades presentation, documentation or tooling; data and results stay correct.' },
        low: { color: tint(NAVY, 0.2), meaning: 'A defect is cosmetic or only affects developer convenience.' }
    };
    // The documentation's system diagrams use the same colours: green for the engine, navy for the application.
    const REPOSITORIES = {
        engine: { label: 'Matching engine', color: GREEN },
        app: { label: 'Review application', color: NAVY }
    };
    // Coverage in steps of 10%: pale navy for little, full navy for all.
    const COVERAGE_RAMP = Array.from({ length: 10 }, (_, step) => tint(NAVY, 0.14 + 0.86 * step / 9));
    const NOT_MEASURED_COLOR = '#e9ecef';
    // The same values as the --color-quality-* tokens.
    const EDGE_COLORS = { declared: MUTED, undeclared: '#e08e0b', unused: '#adb5bd', internal: '#ced4da', crossing: NAVY, contract: PURPLE, clone: INK };
    // The --color-quality-module-1 to -10 tokens: a categorical palette for white, in the order that keeps neighbouring
    // modules apart, including the last slot beside the first.
    const MODULE_PALETTE = ['#2a78d6', '#eb6834', '#17a173', '#99631f', '#d6558a', '#c98500', '#6250d6', '#008300', '#0e93a8', '#e34948'];
    const LINK_KINDS = {
        imports: 'imports', uses: 'names imported or referenced', calls: 'calls', loads: 'script loads', requests: 'HTTP requests',
        renders: 'templates rendered', extends: 'templates extended', includes: 'templates included', links: 'links to pages'
    };
    const UNMATCHED_KINDS = { url: 'URL', endpoint: 'url_for endpoint', template: 'template' };
    const DYNAMIC_KINDS = { request: 'request', url_for: 'url_for', render_template: 'render_template' };
    const STATUS = {
        pass: { label: 'Pass', icon: 'fa-check-circle', tone: 'good' },
        measured: { label: 'Measured', icon: '', tone: 'neutral' },
        fail: { label: 'Fail', icon: 'fa-times-circle', tone: 'bad' },
        attention: { label: 'Needs attention', icon: 'fa-exclamation-triangle', tone: 'warn' },
        invalid: { label: 'Invalid evidence', icon: 'fa-ban', tone: 'bad' },
        not_measured: { label: 'Not measured', icon: '', tone: 'muted' },
        not_applicable: { label: 'Not applicable', icon: '', tone: 'muted' }
    };
    const LANES = [['tests', 'Tests'], ['coverage', 'Branch coverage'], ['duplication', 'Duplicated blocks'], ['docs', 'Docs'], ['architecture', 'Architecture']];
    const LEVELS = {
        modules: { all: 'All modules', unit: 'lines' },
        files: { all: 'All files', unit: 'files' },
        symbols: { all: 'All functions', unit: 'functions' }
    };
    // Modules and Files: the space between the module circles of a column, and between the columns of the two
    // repositories. An arc between two modules bends away from its column by ARC of its length.
    const LAYER_GAP = 46;
    const COLUMN_GAP = 300;
    const ARC = 0.42;
    // The piles of module circles on the Functions level: how far above a dependency a module sits as a share of their
    // radii, the room between piles, and how many places are tried for a circle on each side of where it wants to be.
    const STACK_LIFT = 0.6;
    const STACK_GAP = 60;
    const STACK_STEPS = 400;
    // A code file longer than this is listed as large and ringed on the Files level.
    const FILE_BUDGET = 1000;
    const CODE_FILE = /\.(py|js|mjs|cjs|css|html)$/;
    // A tooltip waits for the cursor to rest, so sweeping across the map shows nothing.
    const HOVER_DELAY = 250;
    const TOOLTIP_GRACE = 120;
    // Dots: steps of the force layout, space between dots, how much larger than its dots a region's disc is, and the
    // space between regions. Each dot keeps clear of the others by DOT_ROOM of its own radius, so zooming in opens
    // gaps where lines and names show instead of only making the dots larger.
    const LAYOUT_TICKS = 120;
    const DOT_GAP = 1.6;
    const DOT_ROOM = 0.6;
    const DOT_SPREAD = 1.6;
    const REGION_GAP = 10;
    // A region's circle: this much wider than its outermost dot. Its name is REGION_LABEL_PX tall on screen.
    const REGION_MARGIN = 5;
    const REGION_LABEL_PX = 12;
    const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
    const SEARCH_LIMIT = 8;
    // A dot found by search opens at least this close, where its neighbours' names can be read.
    const FOCUS_ZOOM = 1.6;
    // A module drawn alone fills the map, but a small one opens no closer than this, so its dots stay dots.
    const MODULE_MAX_ZOOM = 3;
    // Names are placed again once a zoom has rested this long: placing them on every frame made zooming stutter.
    const NAME_DELAY = 120;
    // A dot's name shows once it is at least this tall on screen: at first only on the largest dots.
    // Around a selection every name may show, at least NAMED_FONT map units tall.
    const LABEL_PX = 10;
    // The largest a name grows on screen: zoomed in, names keep this size and take less of the map, so more fit.
    const LABEL_MAX_PX = 13;
    const NAMED_FONT = 9;
    // A findings card shows this many rows; the rest fold away, so one long list does not set the height of the page.
    const FINDING_ROWS = 6;

    function escapeHtml(value) {
        const replacements = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
        return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, (character) => replacements[character]);
    }

    function shortName(moduleId) {
        return moduleId.slice(moduleId.indexOf('.') + 1);
    }

    function repositoryOf(fileId) {
        return fileId.slice(0, fileId.indexOf(':'));
    }

    function pathOf(fileId) {
        return fileId.slice(fileId.indexOf(':') + 1);
    }

    function baseName(fileId) {
        const path = pathOf(fileId);
        return path.slice(path.lastIndexOf('/') + 1);
    }

    function indexBy(rows, key) {
        const index = {};
        rows.forEach((row) => { index[row[key]] = row; });
        return index;
    }

    function fileOwners(codeMap) {
        const owners = {};
        codeMap.files.forEach((file) => { owners[file.id] = file.module; });
        return owners;
    }

    /** A link to a page is listed with its file but draws no arrow: following a link does not use the page's code. */
    function drawn(link) {
        return link.kind !== 'links';
    }

    function symbolFile(symbolId) {
        return symbolId.slice(0, symbolId.lastIndexOf(':'));
    }

    function symbolLine(symbolId) {
        return Number(symbolId.slice(symbolId.lastIndexOf('@') + 1));
    }

    function declaredDependencies(codeMap) {
        const declared = new Set();
        codeMap.modules.forEach((module) => (module.dependencies || []).forEach((dependency) => declared.add(module.id + '>' + dependency)));
        return declared;
    }

    function addCount(target, key, count) {
        target[key] = (target[key] || 0) + count;
    }

    function plural(count, word, words) {
        return count + ' ' + (count === 1 ? word : (words || word + 's'));
    }

    /** Code references between modules, each marked as declared in the catalog or not. Declared dependencies without code have count 0. */
    function aggregateModuleLinks(codeMap) {
        const owners = fileOwners(codeMap);
        const declared = declaredDependencies(codeMap);
        const result = {};
        codeMap.links.filter(drawn).forEach((link) => {
            const source = owners[link.source];
            const target = owners[link.target];
            if (!source || !target || source === target) return;
            const key = source + '>' + target;
            const entry = result[key] || (result[key] = { source, target, count: 0, kinds: {}, links: [], declared: declared.has(key) });
            entry.count += link.count;
            addCount(entry.kinds, link.kind, link.count);
            entry.links.push(link);
        });
        declared.forEach((key) => {
            if (!result[key]) {
                const [source, target] = key.split('>');
                result[key] = { source, target, count: 0, kinds: {}, links: [], declared: true };
            }
        });
        return Object.values(result).sort((a, b) => b.count - a.count || (a.source + a.target).localeCompare(b.source + b.target));
    }

    /** What the map shows about module boundaries, for the findings list and the overview. */
    function boundaryFindings(codeMap, moduleLinks) {
        const used = moduleLinks.filter((link) => link.count > 0);
        const keys = new Set(used.map((link) => link.source + '>' + link.target));
        const privateNames = [];
        Object.keys(codeMap.interface || {}).sort().forEach((moduleId) => codeMap.interface[moduleId].forEach((symbol) => {
            if (/^_[^_]/.test(symbol.name)) privateNames.push(Object.assign({ module: moduleId }, symbol));
        }));
        return {
            undeclared: used.filter((link) => !link.declared),
            cycles: used.filter((link) => link.source < link.target && keys.has(link.target + '>' + link.source)),
            unused: moduleLinks.filter((link) => link.count === 0),
            privateNames
        };
    }

    /** Where reading the code is not enough: references that reach nothing, routes nothing reaches, runtime URLs and ambiguous names. */
    function blindSpots(codeMap) {
        const spots = codeMap.blind_spots || {};
        return {
            unmatched: spots.unmatched || [],
            unreached: (codeMap.routes || []).filter((route) => !route.requested_by.length && !route.linked_by.length),
            dynamic: spots.dynamic || [],
            sharedNames: spots.shared_names || []
        };
    }

    /**
     * What the map points at for cleaning up: functions and classes whose name nothing else in the code mentions,
     * blocks of code found twice, and code files longer than FILE_BUDGET lines, longest first.
     */
    function cleanup(codeMap) {
        return {
            unused: (codeMap.symbols || []).filter((symbol) => symbol.unused),
            clones: codeMap.clones || [],
            large: codeMap.files.filter((file) => CODE_FILE.test(file.id) && (file.lines || 0) > FILE_BUDGET).sort((a, b) => b.lines - a.lines || a.id.localeCompare(b.id))
        };
    }

    /** A module's level is one above its highest declared dependency in the same repository. */
    function moduleLevels(codeMap) {
        const modules = indexBy(codeMap.modules, 'id');
        const levels = {};
        function level(id, visiting) {
            if (levels[id] !== undefined) return levels[id];
            if (visiting.has(id)) return 0;
            visiting.add(id);
            const dependencies = (modules[id].dependencies || []).filter((dependency) => modules[dependency] && modules[dependency].repository === modules[id].repository);
            levels[id] = dependencies.length ? 1 + Math.max(...dependencies.map((dependency) => level(dependency, visiting))) : 0;
            return levels[id];
        }
        codeMap.modules.forEach((module) => level(module.id, new Set()));
        return levels;
    }

    function repositoriesOf(codeMap) {
        const present = Array.from(new Set(codeMap.modules.map((module) => module.repository)));
        return Object.keys(REPOSITORIES).filter((repository) => present.includes(repository))
            .concat(present.filter((repository) => !REPOSITORIES[repository]).sort());
    }

    /** Left-to-right order that keeps connected modules close: a few rounds of sorting by the mean position of each module's neighbours. */
    function moduleOrder(codeMap, ids, levels) {
        const neighbours = {};
        ids.forEach((id) => { neighbours[id] = new Set(); });
        const connect = (a, b) => {
            if (a !== b && neighbours[a] && neighbours[b]) {
                neighbours[a].add(b);
                neighbours[b].add(a);
            }
        };
        const owners = fileOwners(codeMap);
        codeMap.modules.forEach((module) => (module.dependencies || []).forEach((dependency) => connect(module.id, dependency)));
        codeMap.links.filter(drawn).forEach((link) => connect(owners[link.source], owners[link.target]));
        let order = ids.slice().sort((a, b) => levels[b] - levels[a] || a.localeCompare(b));
        for (let round = 0; round < 4; round++) {
            const index = {};
            order.forEach((id, position) => { index[id] = position; });
            const key = (id) => {
                const around = Array.from(neighbours[id]);
                return around.length ? around.reduce((sum, other) => sum + index[other], index[id]) / (around.length + 1) : index[id];
            };
            order = order.slice().sort((a, b) => key(a) - key(b) || index[a] - index[b]);
        }
        return order;
    }

    /** The column of each module on the Modules and Files levels: one for each repository, the largest repository first. */
    function moduleColumns(codeMap) {
        const columns = {};
        repositoriesOf(codeMap).map((repository) => codeMap.modules.filter((module) => module.repository === repository).map((module) => module.id))
            .sort((a, b) => b.length - a.length).forEach((ids, column) => ids.forEach((id) => { columns[id] = column; }));
        return columns;
    }

    /**
     * Centres for the module circles of ``radii``, by module id. Each repository is a column; in it a module sits above
     * the modules it declares as dependencies, and modules of the same level sit side by side. The columns end at the
     * same bottom edge, where the modules that everything else depends on are.
     */
    function layeredCentres(codeMap, radii) {
        const levels = moduleLevels(codeMap);
        const columnOf = moduleColumns(codeMap);
        const columns = [];
        Object.keys(radii).sort().forEach((id) => {
            const rows = columns[columnOf[id]] || (columns[columnOf[id]] = {});
            (rows[levels[id]] = rows[levels[id]] || []).push(id);
        });
        const centres = {};
        const heights = [];
        let left = 0;
        columns.forEach((rows, column) => {
            const wide = (row) => row.reduce((sum, id) => sum + 2 * radii[id], 0) + (row.length - 1) * LAYER_GAP;
            const width = Math.max(...Object.values(rows).map(wide));
            let y = 0;
            Object.keys(rows).map(Number).sort((a, b) => b - a).forEach((level) => {
                const height = 2 * Math.max(...rows[level].map((id) => radii[id]));
                let x = left + (width - wide(rows[level])) / 2;
                rows[level].forEach((id) => {
                    centres[id] = { x: x + radii[id], y: y + height / 2 };
                    x += 2 * radii[id] + LAYER_GAP;
                });
                y += height + LAYER_GAP;
            });
            heights[column] = y - LAYER_GAP;
            left += width + COLUMN_GAP;
        });
        const tallest = Math.max(...heights.filter((height) => height !== undefined));
        Object.keys(centres).forEach((id) => { centres[id].y += tallest - heights[columnOf[id]]; });
        return centres;
    }

    /**
     * The modules as the map stacks them: repository by repository, the largest first, and in each from the module on
     * top to the modules everything else depends on.
     */
    function moduleHierarchy(codeMap) {
        const levels = moduleLevels(codeMap);
        const columns = moduleColumns(codeMap);
        return codeMap.modules.map((module) => module.id)
            .sort((a, b) => columns[a] - columns[b] || levels[b] - levels[a] || a.localeCompare(b));
    }

    /**
     * Centres for the module circles of the Functions level, by module id. The circles are far larger than on the other
     * levels, so a column would be too tall: each repository is a pile instead. Its modules are dropped in from the
     * bottom level up; each comes to rest on the floor or on the ones below it, as low as it can while staying above
     * every module it declares as a dependency, and as close to them as it can. The piles stand on the same floor, in
     * the order of the columns.
     */
    function stackedCentres(codeMap, radii, gap = REGION_GAP) {
        const modules = indexBy(codeMap.modules, 'id');
        const levels = moduleLevels(codeMap);
        const columnOf = moduleColumns(codeMap);
        const piles = [];
        Object.keys(radii).sort().forEach((id) => (piles[columnOf[id]] = piles[columnOf[id]] || []).push(id));
        const centres = {};
        let left = 0;
        piles.forEach((ids) => {
            const span = ids.reduce((sum, id) => sum + 2 * radii[id] + gap, 0);
            const placed = [];
            ids.sort((a, b) => levels[a] - levels[b] || radii[b] - radii[a] || a.localeCompare(b)).forEach((id) => {
                const r = radii[id];
                const below = (modules[id].dependencies || []).map((dependency) => placed.find((disc) => disc.id === dependency)).filter(Boolean);
                const wanted = below.length ? below.reduce((sum, disc) => sum + disc.x, 0) / below.length : 0;
                let best = null;
                for (let step = -STACK_STEPS; step <= STACK_STEPS; step++) {
                    const x = wanted + span * step / STACK_STEPS;
                    let height = r;
                    placed.forEach((disc) => {
                        const reach = r + disc.r + gap;
                        if (Math.abs(x - disc.x) < reach) height = Math.max(height, disc.height + Math.sqrt(reach * reach - (x - disc.x) * (x - disc.x)));
                    });
                    below.forEach((disc) => { height = Math.max(height, disc.height + (r + disc.r) * STACK_LIFT); });
                    height = Math.round(height);
                    if (!best || height < best.height || (height === best.height && Math.abs(x - wanted) < Math.abs(best.x - wanted))) best = { id, x, height, r };
                }
                placed.push(best);
            });
            const start = Math.min(...placed.map((disc) => disc.x - disc.r));
            placed.forEach((disc) => { centres[disc.id] = { x: left + disc.x - start, y: -disc.height }; });
            left += Math.max(...placed.map((disc) => disc.x + disc.r)) - start + STACK_GAP;
        });
        return centres;
    }

    /** File-level links touching ``focusId`` (all links when null), summed over kinds, and the files they connect. */
    function fileGraph(codeMap, focusId) {
        const owners = fileOwners(codeMap);
        const files = indexBy(codeMap.files, 'id');
        const declared = declaredDependencies(codeMap);
        const pairs = {};
        codeMap.links.filter(drawn).forEach((link) => {
            const source = owners[link.source];
            const target = owners[link.target];
            if (!source || !target || (focusId && source !== focusId && target !== focusId)) return;
            const key = link.source + '>' + link.target;
            const entry = pairs[key] || (pairs[key] = {
                source: link.source, target: link.target, count: 0, kinds: {},
                crossing: source !== target, declared: source === target || declared.has(source + '>' + target)
            });
            entry.count += link.count;
            addCount(entry.kinds, link.kind, link.count);
        });
        const links = Object.values(pairs);
        const included = new Set(focusId ? codeMap.files.filter((file) => file.module === focusId).map((file) => file.id) : []);
        links.forEach((link) => { included.add(link.source); included.add(link.target); });
        const entries = new Set(links.filter((link) => link.crossing && (!focusId || owners[link.target] === focusId)).map((link) => link.target));
        return { files: Array.from(included).sort().map((id) => files[id]), links, entries };
    }

    /** Dot diameter of a file. The area grows with its lines, up to 3,000, so one generated file does not dwarf the rest. */
    function fileSize(lines) {
        return Math.round((5 + 0.9 * Math.sqrt(Math.min(lines, 3000))) * 10) / 10;
    }

    /**
     * Every file as one node, sized by its lines; links join two files, summed over kinds. ``group`` is the file's
     * folder, so the files of a folder start side by side. A link to a page draws nothing, as on the other levels.
     */
    function fileDots(codeMap) {
        return {
            nodes: codeMap.files.map((file) => ({
                id: file.id, kind: 'file', name: baseName(file.id), file: file.id, module: file.module, lines: file.lines || 0,
                size: fileSize(file.lines || 0), group: file.id.slice(0, file.id.lastIndexOf('/') + 1),
                large: CODE_FILE.test(file.id) && (file.lines || 0) > FILE_BUDGET
            })),
            links: fileGraph(codeMap, null).links
        };
    }

    /**
     * Every function and class as one node. ``users`` counts the distinct functions and files that use it, ``uses`` the
     * functions it uses, and ``size`` is its dot's diameter; links join two functions, summed over kinds. A link to a page
     * draws nothing, as on the other levels.
     */
    function symbolGraph(codeMap) {
        const owners = fileOwners(codeMap);
        const declared = declaredDependencies(codeMap);
        const symbols = (codeMap.symbols || []).filter((symbol) => owners[symbol.file]);
        const known = indexBy(symbols, 'id');
        const users = {};
        const uses = {};
        const pairs = {};
        (codeMap.symbol_links || []).filter(drawn).forEach((link) => {
            const target = known[link.target];
            if (!target || link.source === link.target) return;
            (users[link.target] = users[link.target] || new Set()).add(link.source);
            const source = known[link.source];
            if (!source) return;
            (uses[link.source] = uses[link.source] || new Set()).add(link.target);
            const sourceModule = owners[source.file];
            const targetModule = owners[target.file];
            const key = link.source + '>' + link.target;
            const entry = pairs[key] || (pairs[key] = {
                source: link.source, target: link.target, count: 0, kinds: {},
                crossing: sourceModule !== targetModule, declared: sourceModule === targetModule || declared.has(sourceModule + '>' + targetModule)
            });
            entry.count += link.count;
            addCount(entry.kinds, link.kind, link.count);
        });
        const size = (sets, id) => (sets[id] ? sets[id].size : 0);
        return {
            nodes: symbols.map((symbol) => ({
                id: symbol.id, kind: 'symbol', name: symbol.name, file: symbol.file, group: symbol.file, line: symbol.line, module: owners[symbol.file],
                users: size(users, symbol.id), uses: size(uses, symbol.id), size: symbolSize(size(users, symbol.id)), unused: Boolean(symbol.unused)
            })),
            links: Object.values(pairs)
        };
    }

    /**
     * One module's functions, to draw it alone: its functions and the links between them. A dot keeps the size its
     * users across every module give it, so it looks the same as on the whole map.
     */
    function moduleSymbolGraph(graph, moduleId) {
        const nodes = graph.nodes.filter((node) => node.module === moduleId);
        const ids = new Set(nodes.map((node) => node.id));
        return { nodes, links: graph.links.filter((link) => ids.has(link.source) && ids.has(link.target)) };
    }

    /** Dot diameter of a function. The area grows with the number of users, so a dot used ten times is not ten times as wide. */
    function symbolSize(users) {
        return Math.round((6 + 4.5 * Math.sqrt(users)) * 10) / 10;
    }

    /** Font size of a dot's name, in map units: a larger dot has a larger name, which shows from further away. */
    function dotFont(size) {
        return Math.round((4 + size * 0.45) * 10) / 10;
    }

    /** The modules around the cloud of functions, repository by repository, with connected modules side by side. */
    function moduleRing(codeMap) {
        const levels = moduleLevels(codeMap);
        return repositoriesOf(codeMap).flatMap((repository) => moduleOrder(codeMap,
            codeMap.modules.filter((module) => module.repository === repository).map((module) => module.id), levels));
    }

    /**
     * Each module's colour: the palette in ring order, starting from the module with the most
     * functions, so neighbouring regions get neighbouring slots and the largest region the first colour.
     */
    function moduleColors(codeMap) {
        const ring = moduleRing(codeMap);
        const owners = fileOwners(codeMap);
        const counts = {};
        (codeMap.symbols || []).forEach((symbol) => addCount(counts, owners[symbol.file], 1));
        const first = ring.reduce((best, id, index) => ((counts[id] || 0) > (counts[ring[best]] || 0) ? index : best), 0);
        const colors = {};
        ring.forEach((id, index) => { colors[id] = MODULE_PALETTE[((index - first + ring.length) % ring.length) % MODULE_PALETTE.length]; });
        return colors;
    }

    /**
     * Centres for discs of ``radii`` packed into one cluster with ``gap`` between them: the discs start side by side on
     * a ring, in the given order, and fall towards the middle until they touch, faster vertically so the cluster comes
     * out wider than tall, like the map. Discs do not deform, so the dots placed in them start without pressure;
     * neighbours on the ring mostly stay neighbours.
     */
    function packRegions(radii, gap = REGION_GAP) {
        const count = radii.length;
        const circumference = radii.reduce((sum, r) => sum + 2 * r + gap, 0);
        const ringRadius = circumference / (2 * Math.PI);
        let arc = 0;
        const centres = radii.map((r) => {
            const angle = (arc + r + gap / 2) / circumference * 2 * Math.PI - Math.PI / 2;
            arc += 2 * r + gap;
            return { x: count > 1 ? Math.cos(angle) * ringRadius : 0, y: count > 1 ? Math.sin(angle) * ringRadius : 0 };
        });
        // The last steps only push discs apart, so none is left overlapping a neighbour.
        for (let step = 0; step < 300; step++) {
            if (step < 240) {
                centres.forEach((centre) => {
                    centre.x *= 0.98;
                    centre.y *= 0.96;
                });
            }
            for (let round = 0; round < 4; round++) {
                for (let a = 0; a < count; a++) {
                    for (let b = a + 1; b < count; b++) {
                        const dx = centres[b].x - centres[a].x;
                        const dy = centres[b].y - centres[a].y;
                        const distance = Math.sqrt(dx * dx + dy * dy) || 1e-6;
                        const overlap = radii[a] + radii[b] + gap - distance;
                        if (overlap <= 0) continue;
                        // The smaller disc gives way more.
                        const share = radii[b] * radii[b] / (radii[a] * radii[a] + radii[b] * radii[b] || 1);
                        centres[a].x -= dx / distance * overlap * share;
                        centres[a].y -= dy / distance * overlap * share;
                        centres[b].x += dx / distance * overlap * (1 - share);
                        centres[b].y += dy / distance * overlap * (1 - share);
                    }
                }
            }
        }
        // Centred on the middle of the cluster's area.
        const area = radii.reduce((sum, r) => sum + r * r, 0) || 1;
        const middleX = centres.reduce((sum, centre, k) => sum + centre.x * radii[k] * radii[k], 0) / area;
        const middleY = centres.reduce((sum, centre, k) => sum + centre.y * radii[k] * radii[k], 0) / area;
        return centres.map((centre) => ({ x: centre.x - middleX, y: centre.y - middleY }));
    }

    /**
     * Places the dots of ``graph`` with a small force layout, run to the end before anything is drawn: ``positions`` by
     * node id, and ``regions``, the circle around the dots of each region, largest first. ``regionOf`` gives a node's
     * region, its module unless told otherwise, and ``place`` the centres of the regions from their ids and radii:
     * packed into one round cloud unless told otherwise.
     *
     * Each region is a disc: its groups of dots, largest first, on a sunflower spiral, and each group's dots on a
     * smaller spiral around the group, so the functions of a file or the files of a folder start in one piece. Each
     * disc is held at its centre as a whole; links inside a region pull dots that use each other closer, and collisions
     * keep the dots apart, each with DOT_ROOM of its radius to spare. A last run of collisions alone parts the dots
     * that links still hold together. No dot leaves its disc, so regions never overlap; each circle drawn is centred on
     * its disc and just wider than its outermost dot. Collisions are found on a grid of cells as wide as the largest
     * pair of dots, so a step costs about as much as there are dots. There is no randomness: the same code map gives
     * the same map.
     */
    function dotLayout(graph, options = {}) {
        const ticks = options.ticks === undefined ? LAYOUT_TICKS : options.ticks;
        const regionOf = options.regionOf || ((node) => node.module);
        const place = options.place || ((ids, radii) => packRegions(radii));
        // A region moves as a whole towards its anchor, so the pull does not crush it; each dot is held only lightly.
        const ANCHOR = 0.08;
        const HOLD = 0.008;
        const SETTLE = 0.6;
        const LINK_INSIDE = 0.3;
        const LINK_GAP = 8;
        const COLLIDE = 0.7;
        const FRICTION = 0.45;
        const ALPHA_END = 0.02;
        const SEPARATE_TICKS = 60;
        const count = graph.nodes.length;
        const positions = {};
        if (!count) return { positions, regions: [] };
        const radius = new Float64Array(count);
        const room = new Float64Array(count);
        const x = new Float64Array(count);
        const y = new Float64Array(count);
        const vx = new Float64Array(count);
        const vy = new Float64Array(count);
        const region = new Int32Array(count);
        const index = {};
        const byRegion = {};
        graph.nodes.forEach((node, i) => {
            index[node.id] = i;
            radius[i] = node.size / 2;
            room[i] = radius[i] * (1 + DOT_ROOM) + DOT_GAP;
            const files = byRegion[regionOf(node)] || (byRegion[regionOf(node)] = {});
            (files[node.group] = files[node.group] || []).push(i);
        });
        const footprint = (i) => Math.PI * room[i] * room[i] * DOT_SPREAD;
        // By name, so a folder stays together.
        const ring = Object.keys(byRegion).sort();
        const discs = {};
        ring.forEach((regionId) => {
            const files = byRegion[regionId];
            let area = 0;
            Object.keys(files).sort((a, b) => files[b].length - files[a].length || a.localeCompare(b)).forEach((file, fileIndex) => {
                const members = files[file].sort((a, b) => graph.nodes[b].size - graph.nodes[a].size || (graph.nodes[a].line || 0) - (graph.nodes[b].line || 0));
                const fileArea = members.reduce((sum, i) => sum + footprint(i), 0);
                const distance = fileIndex ? Math.sqrt((area + fileArea / 2) / Math.PI) : 0;
                let inner = 0;
                members.forEach((i, k) => {
                    const at = k ? Math.sqrt((inner + footprint(i) / 2) / Math.PI) : 0;
                    inner += footprint(i);
                    x[i] = Math.cos(fileIndex * GOLDEN_ANGLE) * distance + Math.cos(k * GOLDEN_ANGLE) * at;
                    y[i] = Math.sin(fileIndex * GOLDEN_ANGLE) * distance + Math.sin(k * GOLDEN_ANGLE) * at;
                });
                area += fileArea;
            });
            discs[regionId] = Math.sqrt(area / Math.PI);
        });
        // The circles drawn, a margin wider than the discs, are what is packed, so neighbouring circles keep REGION_GAP apart.
        const centres = place(ring, ring.map((regionId) => discs[regionId] + REGION_MARGIN));
        const anchorX = Float64Array.from(centres, (centre) => centre.x);
        const anchorY = Float64Array.from(centres, (centre) => centre.y);
        const discRadius = Float64Array.from(ring, (regionId) => discs[regionId]);
        ring.forEach((regionId, m) => Object.values(byRegion[regionId]).forEach((members) => members.forEach((i) => {
            x[i] += anchorX[m];
            y[i] += anchorY[m];
            region[i] = m;
        })));

        // Only links inside a region pull: held in its disc, a dot pulled towards another region would only pile up on
        // the disc's edge.
        const links = graph.links.filter((link) => index[link.source] !== undefined && index[link.target] !== undefined
            && region[index[link.source]] === region[index[link.target]]);
        const sources = new Int32Array(links.length);
        const targets = new Int32Array(links.length);
        const degree = new Float64Array(count);
        links.forEach((link, k) => {
            sources[k] = index[link.source];
            targets[k] = index[link.target];
            degree[sources[k]] += 1;
            degree[targets[k]] += 1;
        });
        // As in d3-force: a link moves the end with fewer links more, and a busy node is held by each link less.
        const strength = new Float64Array(links.length);
        const bias = new Float64Array(links.length);
        const rest = new Float64Array(links.length);
        links.forEach((link, k) => {
            const source = sources[k];
            const target = targets[k];
            strength[k] = LINK_INSIDE / Math.min(degree[source], degree[target]);
            bias[k] = degree[source] / (degree[source] + degree[target]);
            rest[k] = room[source] + room[target] + LINK_GAP;
        });

        let reach = 0;
        for (let i = 0; i < count; i++) reach = Math.max(reach, room[i]);
        const cellOf = new Int32Array(count);
        const byCell = new Int32Array(count);
        function collide() {
            let left = Infinity;
            let top = Infinity;
            let right = -Infinity;
            let bottom = -Infinity;
            for (let i = 0; i < count; i++) {
                left = Math.min(left, x[i] + vx[i]);
                right = Math.max(right, x[i] + vx[i]);
                top = Math.min(top, y[i] + vy[i]);
                bottom = Math.max(bottom, y[i] + vy[i]);
            }
            // Cells at least as wide as the widest pair of touching dots, and never more than 512 a side.
            const cell = Math.max(2 * reach, (right - left) / 512, (bottom - top) / 512);
            const columns = Math.floor((right - left) / cell) + 1;
            const rows = Math.floor((bottom - top) / cell) + 1;
            const start = new Int32Array(columns * rows + 1);
            for (let i = 0; i < count; i++) {
                cellOf[i] = Math.floor((x[i] + vx[i] - left) / cell) + Math.floor((y[i] + vy[i] - top) / cell) * columns;
                start[cellOf[i] + 1] += 1;
            }
            for (let c = 0; c < columns * rows; c++) start[c + 1] += start[c];
            const fill = start.slice();
            for (let i = 0; i < count; i++) byCell[fill[cellOf[i]]++] = i;
            for (let i = 0; i < count; i++) {
                const px = x[i] + vx[i];
                const py = y[i] + vy[i];
                const column = cellOf[i] % columns;
                const row = (cellOf[i] - column) / columns;
                for (let r = Math.max(0, row - 1); r <= Math.min(rows - 1, row + 1); r++) {
                    for (let c = Math.max(0, column - 1); c <= Math.min(columns - 1, column + 1); c++) {
                        for (let s = start[r * columns + c]; s < start[r * columns + c + 1]; s++) {
                            const j = byCell[s];
                            if (j <= i) continue;
                            let dx = px - x[j] - vx[j];
                            let dy = py - y[j] - vy[j];
                            const least = room[i] + room[j];
                            let length = dx * dx + dy * dy;
                            if (length >= least * least) continue;
                            if (!length) {
                                dx = (j - i) * 1e-3;
                                dy = 1e-3;
                                length = dx * dx + dy * dy;
                            }
                            length = Math.sqrt(length);
                            const push = (least - length) / length * COLLIDE;
                            // The smaller dot gives way more.
                            const share = radius[j] * radius[j] / (radius[i] * radius[i] + radius[j] * radius[j]);
                            vx[i] += dx * push * share;
                            vy[i] += dy * push * share;
                            vx[j] -= dx * push * (1 - share);
                            vy[j] -= dy * push * (1 - share);
                        }
                    }
                }
            }
        }

        /** Moves each dot by its velocity, slowed by ``friction``; a dot that would leave its disc stays on its edge. */
        function move(friction) {
            for (let i = 0; i < count; i++) {
                vx[i] *= 1 - friction;
                vy[i] *= 1 - friction;
                x[i] += vx[i];
                y[i] += vy[i];
                const m = region[i];
                const dx = x[i] - anchorX[m];
                const dy = y[i] - anchorY[m];
                const limit = Math.max(0, discRadius[m] - radius[i]);
                const distance = Math.sqrt(dx * dx + dy * dy);
                if (distance > limit) {
                    x[i] = anchorX[m] + dx / distance * limit;
                    y[i] = anchorY[m] + dy / distance * limit;
                }
            }
        }

        const centreX = new Float64Array(ring.length);
        const centreY = new Float64Array(ring.length);
        const regionSize = new Float64Array(ring.length);
        for (let i = 0; i < count; i++) regionSize[region[i]] += 1;
        for (let tick = 0; tick < ticks; tick++) {
            const alpha = Math.pow(ALPHA_END, tick / Math.max(1, ticks - 1));
            centreX.fill(0);
            centreY.fill(0);
            for (let i = 0; i < count; i++) {
                centreX[region[i]] += x[i] / regionSize[region[i]];
                centreY[region[i]] += y[i] / regionSize[region[i]];
            }
            // The last steps only settle: without the anchors' pressure, collisions part every dot.
            const pull = tick < ticks * SETTLE ? alpha : 0;
            for (let i = 0; pull && i < count; i++) {
                const m = region[i];
                vx[i] += ((anchorX[m] - centreX[m]) * ANCHOR + (anchorX[m] - x[i]) * HOLD) * pull;
                vy[i] += ((anchorY[m] - centreY[m]) * ANCHOR + (anchorY[m] - y[i]) * HOLD) * pull;
            }
            for (let k = 0; k < links.length; k++) {
                const source = sources[k];
                const target = targets[k];
                let dx = x[target] + vx[target] - x[source] - vx[source];
                let dy = y[target] + vy[target] - y[source] - vy[source];
                const length = Math.sqrt(dx * dx + dy * dy) || 1e-3;
                const pull = (length - rest[k]) / length * alpha * strength[k];
                dx *= pull;
                dy *= pull;
                vx[target] -= dx * bias[k];
                vy[target] -= dy * bias[k];
                vx[source] += dx * (1 - bias[k]);
                vy[source] += dy * (1 - bias[k]);
            }
            collide();
            move(FRICTION);
        }
        // Then only collisions, each step taken in full: links can still hold a busy function's callers too close.
        for (let tick = 0; tick < SEPARATE_TICKS; tick++) {
            vx.fill(0);
            vy.fill(0);
            collide();
            move(0);
        }
        graph.nodes.forEach((node, i) => { positions[node.id] = { x: Math.round(x[i] * 10) / 10, y: Math.round(y[i] * 10) / 10 }; });
        // Each circle is centred on its disc and just wider than its outermost dot, so it never reaches a neighbour's.
        const reachOf = new Float64Array(ring.length);
        for (let i = 0; i < count; i++) {
            const m = region[i];
            reachOf[m] = Math.max(reachOf[m], Math.hypot(x[i] - anchorX[m], y[i] - anchorY[m]) + radius[i]);
        }
        const round = (value) => Math.round(value * 10) / 10;
        const regions = ring.map((id, m) => ({ id, x: round(anchorX[m]), y: round(anchorY[m]), r: round(reachOf[m] + REGION_MARGIN), count: regionSize[m] }))
            .sort((a, b) => b.count - a.count || a.id.localeCompare(b.id));
        return { positions, regions };
    }

    /**
     * What one level of the map draws: its dots, their positions and the circles around them, each laid out once.
     * Modules and Files share one layout, the files in module circles placed in columns. Functions piles its larger
     * module circles in the same order, or, with ``moduleId``, draws that module alone with a circle for each file.
     */
    function mapView(context, level, moduleId) {
        const codeMap = context.data.code_map;
        const alone = level === 'symbols' && Boolean(moduleId);
        const key = level !== 'symbols' ? 'files' : 'symbols:' + (moduleId || '');
        if (!context.views[key]) {
            // Module circles go where the hierarchy puts them: in columns, or in piles for the larger circles of Functions.
            const hierarchy = (centresOf) => ({ place: (ids, radii) => {
                const centres = centresOf(codeMap, Object.fromEntries(ids.map((id, index) => [id, radii[index]])));
                return ids.map((id) => centres[id]);
            } });
            let graph = context.symbolGraph;
            let options = hierarchy(stackedCentres);
            if (level !== 'symbols') {
                graph = fileDots(codeMap);
                options = hierarchy(layeredCentres);
            } else if (alone) {
                graph = moduleSymbolGraph(context.symbolGraph, moduleId);
                options = { regionOf: (node) => node.file };
            }
            const { positions, regions } = dotLayout(graph, options);
            regions.forEach((region) => Object.assign(region, { of: alone ? 'file' : 'module', label: alone ? baseName(region.id) : shortName(region.id) }));
            context.views[key] = { graph, positions, regions };
        }
        return context.views[key];
    }

    /**
     * Functions, classes and files whose name matches ``query``, best first: the exact name, a name starting with it, a
     * name containing it, then a path containing it. Ties go to the most used function and the longest file.
     */
    function matchNames(symbols, files, query, limit = SEARCH_LIMIT) {
        const text = String(query || '').trim().toLowerCase();
        if (!text) return [];
        const rank = (name, path) => (name === text ? 0 : name.startsWith(text) ? 1 : name.includes(text) ? 2 : path.includes(text) ? 3 : -1);
        const matches = [];
        symbols.forEach((node) => {
            const score = rank(node.name.toLowerCase(), (pathOf(node.file) + ':' + node.name).toLowerCase());
            if (score >= 0) matches.push({ kind: 'symbol', id: node.id, name: node.name, detail: pathOf(node.file) + ':' + node.line, score, weight: node.users });
        });
        files.forEach((file) => {
            const score = rank(baseName(file.id).toLowerCase(), pathOf(file.id).toLowerCase());
            if (score >= 0) {
                matches.push({ kind: 'file', id: file.id, name: baseName(file.id), score, weight: file.lines || 0,
                    detail: pathOf(file.id) + ' · ' + plural(file.lines || 0, 'line') });
            }
        });
        return matches.sort((a, b) => a.score - b.score || b.weight - a.weight || a.name.localeCompare(b.name) || a.id.localeCompare(b.id))
            .slice(0, limit).map(({ kind, id, name, detail }) => ({ kind, id, name, detail }));
    }

    /**
     * The names to show on the map at ``zoom``: largest dots first, each name at least LABEL_PX tall on
     * screen and kept only if its box, below the dot or else above it, does not overlap a name already kept. With
     * ``only``, the names of those dots whatever their size, ``first`` before the others, as for a selection and its
     * neighbours. ``measure(label, size)`` gives a label's width at a font size. A kept name has ``above`` set when it
     * goes above its dot.
     *
     * The names of ``map.regions`` come first, REGION_LABEL_PX tall on the top of their circle, largest region first
     * and kept only if they do not overlap: the names of dots then go around them. Their ids start with ``region-label:``.
     */
    function labelPlaces(map, zoom, options = {}) {
        const measure = options.measure || ((label, size) => labelWidth(label, size, 600));
        const only = options.only || null;
        const cap = Math.round((LABEL_MAX_PX / zoom) * 10) / 10;
        const fontOf = (node) => Math.min(cap, only ? Math.max(dotFont(node.size), NAMED_FONT) : dotFont(node.size));
        const least = LABEL_PX / zoom;
        const margin = 2 / zoom;
        const cell = 80 / zoom;
        const placed = new Map();
        const kept = [];
        const candidates = map.graph.nodes.filter((node) => (only ? only.has(node.id) : dotFont(node.size) >= least))
            .sort((a, b) => (b.id === options.first) - (a.id === options.first) || b.size - a.size || a.id.localeCompare(b.id));
        const cellsOf = (box) => {
            const keys = [];
            for (let column = Math.floor(box.x1 / cell); column <= Math.floor(box.x2 / cell); column++) {
                for (let row = Math.floor(box.y1 / cell); row <= Math.floor(box.y2 / cell); row++) keys.push(column + ':' + row);
            }
            return keys;
        };
        const add = (box) => cellsOf(box).forEach((key) => (placed.get(key) || placed.set(key, []).get(key)).push(box));
        const body = (node) => {
            const position = map.positions[node.id];
            const half = node.size / 2;
            return { x1: position.x - half, x2: position.x + half, y1: position.y - half, y2: position.y + half };
        };
        const free = (box) => !cellsOf(box).some((key) => (placed.get(key) || [])
            .some((other) => box.x1 < other.x2 && other.x1 < box.x2 && box.y1 < other.y2 && other.y1 < box.y2));
        const regionFont = Math.round((REGION_LABEL_PX / zoom) * 10) / 10;
        (map.regions || []).forEach((region) => {
            const width = measure(region.label, regionFont) + 6 * margin;
            const height = regionFont * 1.25 + 2 * margin;
            const box = { id: 'region-label:' + region.id, x1: region.x - width / 2, x2: region.x + width / 2, y1: region.y - region.r - height / 2, y2: region.y - region.r + height / 2 };
            if (!free(box)) return;
            add(box);
            kept.push(Object.assign(box, { font: regionFont }));
        });
        // A named dot is drawn above the smaller ones, so its own disc is an obstacle for their names.
        const place = (node, always) => {
            const font = fontOf(node);
            const position = map.positions[node.id];
            const width = measure(node.name, font) + 2 * margin;
            const half = node.size / 2;
            const height = font * 1.25 + margin;
            const boxes = [false, true].map((above) => ({
                id: node.id, above, x1: position.x - width / 2, x2: position.x + width / 2,
                y1: above ? position.y - half - height : position.y + half, y2: above ? position.y - half : position.y + half + height
            }));
            const box = always ? boxes[0] : boxes.find(free);
            if (!box) return;
            add(box);
            if (!only) add(body(node));
            kept.push(Object.assign(box, { font }));
        };
        // The selected dot is always named. Around it, all the dots that stay lit are obstacles, so no name covers one.
        const first = candidates.length && candidates[0].id === options.first ? candidates.shift() : null;
        if (first) place(first, true);
        if (only) candidates.forEach((node) => add(body(node)));
        candidates.forEach((node) => place(node, false));
        return kept;
    }

    function moduleLines(codeMap) {
        const lines = {};
        codeMap.files.forEach((file) => addCount(lines, file.module, file.lines || 0));
        return lines;
    }

    /** Branch coverage of a module or a file, or its line coverage when it has no branches; null when not measured. */
    function coverageOf(measurement) {
        if (!measurement) return null;
        return typeof measurement.branches === 'number' ? measurement.branches : typeof measurement.lines === 'number' ? measurement.lines : null;
    }

    function coverageColor(measurement) {
        const value = coverageOf(measurement);
        return value === null ? NOT_MEASURED_COLOR : COVERAGE_RAMP[Math.min(COVERAGE_RAMP.length - 1, Math.floor(value / 10))];
    }

    /**
     * The colour of a module, or of one of its files or functions when ``fileId`` is given. ``colors`` gives each
     * module its own colour; coverage is the file's own when the report has it.
     */
    function nodeColor(module, report, colorBy, colors, fileId) {
        if (!module) return NOT_MEASURED_COLOR;
        if (colorBy === 'repository') return (REPOSITORIES[module.repository] || {}).color || NOT_MEASURED_COLOR;
        if (colorBy === 'coverage') return coverageColor(fileId ? (report.files || {})[fileId] : ((report.modules || {})[module.id] || {}).coverage);
        if (colorBy === 'criticality') return (CRITICALITY[module.criticality] || {}).color || NOT_MEASURED_COLOR;
        return (colors || {})[module.id] || NOT_MEASURED_COLOR;
    }

    function edgeWidth(count) {
        return Math.min(4.5, 1.2 + 0.55 * Math.log2(1 + count));
    }

    /** Plain-language value of one report lane, with its status. */
    function laneSummary(row, lane) {
        const item = (row && row[lane]) || { status: 'not_measured' };
        const status = STATUS[item.status] ? item.status : 'not_measured';
        let text = STATUS[status].label;
        let detail = '';
        if (lane === 'tests' && typeof item.count === 'number' && item.count) {
            text = plural(item.count, 'test');
            const notes = [];
            if (item.skipped) notes.push(item.skipped + ' skipped');
            if ((item.missing_files || []).length) notes.push(plural(item.missing_files.length, 'declared test file') + ' without results');
            detail = notes.join(', ');
        } else if (lane === 'coverage' && typeof item.branches === 'number') {
            text = item.branches + '%';
            detail = typeof item.lines === 'number' ? item.lines + '% of lines' : '';
        } else if (lane === 'duplication' && typeof item.count === 'number') {
            text = String(item.count);
            detail = item.new ? item.new + ' new since the reviewed baseline' : 'none new since the reviewed baseline';
        } else if (lane === 'docs' && typeof item.required === 'number') {
            text = (item.satisfied || 0) + '/' + item.required;
            detail = 'required catalog documentation slots filled';
        } else if (lane === 'architecture' && Array.isArray(item.violations) && item.violations.length) {
            text = plural(item.violations.length, 'forbidden import');
        }
        return { status, text, detail };
    }

    /** A value with its status. Only pass, fail and attention get an icon; missing values are muted text. */
    function statusBadge(status, text) {
        const meta = STATUS[status] || STATUS.not_measured;
        return '<span class="quality-status quality-status--' + meta.tone + '"' + (meta.tone === 'muted' ? ' title="' + escapeHtml(meta.label) + '"' : '') + '>'
            + (meta.icon ? '<i class="fas ' + meta.icon + '" aria-hidden="true"></i>' : '')
            + '<span class="visually-hidden">' + escapeHtml(meta.label) + ': </span>' + escapeHtml(text || meta.label) + '</span>';
    }

    function criticalityBadge(criticality) {
        const meta = CRITICALITY[criticality];
        return '<span class="quality-criticality" title="' + escapeHtml(meta ? meta.meaning : '') + '">'
            + '<span class="quality-swatch" style="background:' + (meta ? meta.color : NOT_MEASURED_COLOR) + '" aria-hidden="true"></span>'
            + escapeHtml(criticality) + '</span>';
    }

    function kindsText(kinds) {
        return Object.keys(LINK_KINDS).filter((kind) => kinds[kind]).map((kind) => kinds[kind] + ' ' + LINK_KINDS[kind]).join(', ');
    }

    /**
     * The elements of one level. Modules: each module's circle, filled, the references between modules as arcs and the
     * contracts between the repositories. Files and Functions: a light circle for each region, a module or a file,
     * and in it a dot for each file or function with the links between dots as thin lines. Files also draws each pair
     * of copied blocks as a dashed line between its two files.
     */
    function mapElements(context, state, view) {
        const codeMap = context.data.code_map;
        const color = (moduleId, fileId) => nodeColor(context.modules[moduleId], context.report, state.colorBy, context.colors, fileId);
        const labels = view.regions.map((region) => ({
            group: 'nodes', classes: 'region-label', position: { x: region.x, y: region.y - region.r },
            data: { id: 'region-label:' + region.id, kind: 'region-label', label: region.label }
        }));
        if (state.level === 'modules') {
            const columns = moduleColumns(codeMap);
            const at = indexBy(view.regions, 'id');
            const elements = view.regions.map((region) => ({
                group: 'nodes', classes: 'module', position: { x: region.x, y: region.y },
                data: { id: region.id, kind: 'module', size: 2 * region.r, color: color(region.id) }
            })).concat(labels);
            const taken = new Set();
            (codeMap.contracts || []).forEach((contract) => {
                const ends = contract.producers.concat(contract.consumers).filter((id) => at[id]);
                if (!ends.length) return;
                const id = 'contract:' + contract.id;
                // Between the columns it joins, and never on another contract.
                const x = Math.round(ends.reduce((sum, end) => sum + at[end].x, 0) / ends.length);
                let y = Math.round(ends.reduce((sum, end) => sum + at[end].y, 0) / ends.length);
                while (taken.has(y)) y += 2 * LAYER_GAP;
                taken.add(y);
                elements.push({ group: 'nodes', classes: 'contract', position: { x, y }, data: { id, label: contract.title, kind: 'contract' } });
                ends.forEach((end) => elements.push({ group: 'edges', classes: 'contract-link', data: { id: id + '~' + end, source: end, target: id, kind: 'contract-link' } }));
            });
            // A declared dependency without code is always drawn: it should not exist, so it is there to be seen and removed.
            context.moduleLinks.filter((link) => at[link.source] && at[link.target]).forEach((link) => {
                const length = Math.hypot(at[link.target].x - at[link.source].x, at[link.target].y - at[link.source].y);
                // A positive arc bends to the right of its direction: for a reference that follows the layering, down
                // the first column, that is outwards. One that goes against the layering bends the other way, inwards.
                const away = columns[link.source] === columns[link.target] ? (columns[link.source] ? -1 : 1) : 0;
                elements.push({
                    group: 'edges', classes: 'module-link ' + (link.count === 0 ? 'unused' : link.declared ? 'declared' : 'undeclared'),
                    data: {
                        id: 'link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'module-link',
                        width: link.count ? edgeWidth(link.count) : 1.2, arc: Math.round(away * ARC * length), label: link.count ? String(link.count) : ''
                    }
                });
            });
            return elements;
        }
        const elements = view.regions.map((region) => ({
            group: 'nodes', classes: 'region', position: { x: region.x, y: region.y },
            data: { id: 'region:' + region.id, kind: 'region', region: region.id, of: region.of, size: 2 * region.r, count: region.count }
        })).concat(labels);
        view.graph.nodes.forEach((node) => elements.push({
            group: 'nodes', classes: 'dot' + (node.unused ? ' unused' : '') + (node.large ? ' large' : ''), position: view.positions[node.id],
            data: { id: node.id, label: node.name, kind: node.kind, module: node.module, file: node.file, size: node.size, font: dotFont(node.size), color: color(node.module, node.file) }
        }));
        view.graph.links.forEach((link) => elements.push({
            group: 'edges', classes: 'dot-link ' + (!link.crossing ? 'internal' : link.declared ? 'crossing' : 'crossing undeclared'),
            data: { id: 'dot-link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'dot-link', kinds: kindsText(link.kinds) }
        }));
        if (state.level === 'files') {
            (codeMap.clones || []).forEach((clone, index) => {
                if (clone.files[0] === clone.files[1] || !view.positions[clone.files[0]] || !view.positions[clone.files[1]]) return;
                elements.push({ group: 'edges', classes: 'clone', data: { id: 'clone:' + index, source: clone.files[0], target: clone.files[1], kind: 'clone', clone: index } });
            });
        }
        return elements;
    }

    /** Box width that fits a label: measured on a canvas once per label, estimated where there is no canvas. */
    const labelWidths = new Map();
    let measuring = null;
    function labelWidth(label, size, weight) {
        const key = weight + ' ' + size + ' ' + label;
        if (!labelWidths.has(key)) {
            if (measuring === null) {
                const canvas = global.document && global.document.createElement('canvas');
                measuring = (canvas && canvas.getContext && canvas.getContext('2d')) || false;
            }
            let width = label.length * size * 0.58;
            if (measuring) {
                measuring.font = weight + ' ' + size + 'px ' + FONT;
                width = measuring.measureText(label).width;
            }
            labelWidths.set(key, Math.ceil(width));
        }
        return labelWidths.get(key);
    }

    const GRAPH_STYLE = [
        { selector: 'node', style: { 'font-family': FONT, color: INK, 'font-size': 12, 'transition-property': 'opacity', 'transition-duration': 150 } },
        { selector: 'edge', style: {
            'curve-style': 'straight', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.8, 'line-color': EDGE_COLORS.declared,
            'target-arrow-color': EDGE_COLORS.declared, 'line-opacity': 0.55, 'transition-property': 'opacity, line-opacity', 'transition-duration': 150
        } },
        // Modules level: a filled circle for each module, and one arc for each pair of modules whose code is linked.
        { selector: 'node.module', style: {
            shape: 'ellipse', width: 'data(size)', height: 'data(size)', 'background-color': 'data(color)', 'border-width': 0, label: '',
            'underlay-color': NAVY, 'underlay-opacity': 0, 'underlay-padding': 8, 'underlay-shape': 'ellipse', 'z-index-compare': 'manual', 'z-index': 0
        } },
        { selector: 'node.contract', style: {
            shape: 'diamond', width: 30, height: 30, 'background-color': PURPLE, label: 'data(label)',
            'text-valign': 'bottom', 'text-margin-y': 6, 'text-wrap': 'wrap', 'text-max-width': 190, 'font-size': 22, 'font-weight': 600, color: PURPLE,
            'text-background-color': '#ffffff', 'text-background-opacity': 0.9, 'text-background-padding': 2, 'text-background-shape': 'round-rectangle'
        } },
        { selector: 'edge.module-link', style: {
            width: 'data(width)', 'curve-style': 'unbundled-bezier', 'control-point-distances': (edge) => edge.data('arc'), 'control-point-weights': 0.5,
            'line-opacity': 0.7
        } },
        { selector: 'edge.unused', style: { 'line-color': EDGE_COLORS.unused, 'target-arrow-color': EDGE_COLORS.unused, 'line-style': 'dotted', 'line-opacity': 0.9 } },
        { selector: 'edge.undeclared', style: {
            'line-color': EDGE_COLORS.undeclared, 'target-arrow-color': EDGE_COLORS.undeclared, 'line-style': 'dashed', 'line-dash-pattern': [7, 4], 'line-opacity': 0.9
        } },
        { selector: 'edge.contract-link', style: {
            width: 1.5, 'line-color': EDGE_COLORS.contract, 'line-style': 'dotted', 'target-arrow-shape': 'none', 'line-opacity': 0.6
        } },
        // Files and Functions levels. Only dots marked .labelled show their name, which the script sets from the zoom
        // (LABEL_PX), so at first only the largest dots are named and more names appear when zoomed in, at most
        // LABEL_MAX_PX tall. Lines are thin and faint, and let clicks through to the dots.
        { selector: 'node.dot', style: {
            shape: 'ellipse', width: 'data(size)', height: 'data(size)', 'background-color': 'data(color)', 'border-width': 0,
            label: '', 'font-size': 'data(font)', 'font-weight': 600, color: INK, 'text-valign': 'bottom', 'text-halign': 'center',
            'text-margin-y': 1, 'text-outline-color': '#ffffff', 'text-outline-width': 1.5, 'text-outline-opacity': 0.9,
            'z-index-compare': 'manual', 'z-index': (node) => 2 + Math.round(node.data('size')), 'underlay-color': NAVY, 'underlay-opacity': 0, 'underlay-padding': 3,
            'underlay-shape': 'ellipse', 'transition-duration': 0
        } },
        // A function nothing mentions is hollow; a file over the size budget is ringed.
        { selector: 'node.dot.unused', style: { 'background-color': '#ffffff', 'border-width': 1.4, 'border-color': 'data(color)' } },
        { selector: 'node.dot.large', style: { 'outline-width': 1.5, 'outline-color': INK, 'outline-opacity': 0.7, 'outline-offset': 2 } },
        // A named dot is drawn above the unnamed ones, so no dot covers a name.
        { selector: 'node.dot.labelled', style: { label: 'data(label)', 'font-size': (node) => node.data('labelFont') || node.data('font'), 'z-index': (node) => 500 + Math.round(node.data('size')) } },
        { selector: 'node.dot.above', style: { 'text-valign': 'top', 'text-margin-y': -1 } },
        { selector: 'node.dot.unlabelled', style: { label: '' } },
        { selector: 'edge.dot-link', style: {
            'curve-style': 'haystack', 'haystack-radius': 0, width: 0.6, 'line-color': EDGE_COLORS.unused, 'line-style': 'solid',
            'line-opacity': 0.4, 'target-arrow-shape': 'none', events: 'no', 'transition-duration': 0, 'z-index-compare': 'manual', 'z-index': 1
        } },
        { selector: 'edge.dot-link.hidden', style: { display: 'none' } },
        { selector: 'edge.clone', style: {
            width: 1.6, 'line-color': EDGE_COLORS.clone, 'line-style': 'dashed', 'line-dash-pattern': [3, 3], 'line-opacity': 0.75,
            'target-arrow-shape': 'none', 'z-index-compare': 'manual', 'z-index': 400
        } },
        // Regions: a light circle under each module's or file's dots, below the lines; its name, placed like the dots'
        // names, sits on top of everything on the circle's edge.
        { selector: 'node.region', style: {
            shape: 'ellipse', width: 'data(size)', height: 'data(size)', 'background-color': '#f8f9fa', 'background-opacity': 1,
            'border-width': 0.75, 'border-color': EDGE_COLORS.internal, label: '', 'z-index-compare': 'manual', 'z-index': 0,
            'underlay-shape': 'ellipse', 'transition-duration': 0
        } },
        { selector: 'node.region.hover', style: { 'background-color': NOT_MEASURED_COLOR, 'border-width': 1.5, 'border-color': MUTED, 'underlay-opacity': 0 } },
        { selector: 'node.region-label', style: {
            shape: 'ellipse', width: 1, height: 1, 'background-opacity': 0, 'border-width': 0, label: '', events: 'no',
            'font-weight': 700, color: MUTED, 'text-valign': 'center', 'text-halign': 'center',
            'text-background-color': '#ffffff', 'text-background-opacity': 0.92, 'text-background-shape': 'round-rectangle',
            'text-background-padding': (node) => (node.data('labelFont') || 4) * 0.25,
            'text-border-width': (node) => (node.data('labelFont') || 4) * 0.08, 'text-border-color': EDGE_COLORS.internal, 'text-border-opacity': 1,
            'z-index-compare': 'manual', 'z-index': 2000, 'transition-duration': 0
        } },
        { selector: 'node.region-label.labelled', style: { label: 'data(label)', 'font-size': (node) => node.data('labelFont') || 4 } },
        // Focus, from a click: the rest of the map steps back but stays readable.
        { selector: '.faded', style: { opacity: 0.3 } },
        { selector: 'edge.lit', style: { 'line-opacity': 1, 'z-index': 10 } },
        { selector: 'edge.lit[label]', style: {
            label: 'data(label)', 'font-family': FONT, 'font-size': 11, 'font-weight': 600, color: INK, 'text-rotation': 'none',
            'text-background-color': '#ffffff', 'text-background-opacity': 1, 'text-background-padding': 3, 'text-background-shape': 'round-rectangle',
            'text-border-width': 1, 'text-border-color': '#e5e7eb', 'text-border-opacity': 1
        } },
        // Hover only marks: a halo on the circle or dot and thicker lines of its own. Nothing else changes.
        { selector: 'node.module.hover', style: { 'underlay-opacity': 0.16 } },
        { selector: 'edge.hover', style: { width: (edge) => (edge.data('width') || 1.5) + 1.5, 'line-opacity': 1, 'z-index': 9 } },
        // A selected dot's own lines keep their meaning: grey inside its module, navy or orange across a boundary.
        { selector: 'edge.dot-link.lit, edge.dot-link.hover', style: {
            display: 'element', 'curve-style': 'straight', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.5, width: 1.1,
            'line-color': EDGE_COLORS.declared, 'target-arrow-color': EDGE_COLORS.declared, 'line-opacity': 0.85, 'z-index': 10
        } },
        { selector: 'edge.dot-link.lit.crossing', style: { 'line-color': NAVY, 'target-arrow-color': NAVY } },
        { selector: 'edge.dot-link.lit.undeclared', style: {
            'line-color': EDGE_COLORS.undeclared, 'target-arrow-color': EDGE_COLORS.undeclared, 'line-style': 'dashed', 'line-dash-pattern': [5, 3]
        } },
        // Faded dots drop their names, so the names of the selection and its neighbours stand out.
        { selector: 'node.dot.faded', style: { opacity: 0.16, label: '' } },
        { selector: 'edge.dot-link.faded', style: { opacity: 0.08 } },
        { selector: 'node.dot.named', style: { label: 'data(label)', 'font-size': (node) => node.data('labelFont') || Math.max(node.data('font'), NAMED_FONT), 'z-index': 1000 } },
        { selector: 'node.dot.hover', style: { 'border-width': 1.5, 'border-color': INK, 'underlay-opacity': 0.18 } },
        { selector: 'node:selected', style: { 'underlay-opacity': 0.3, 'underlay-padding': 6 } },
        { selector: 'edge:selected', style: { 'underlay-color': NAVY, 'underlay-opacity': 0.2, 'underlay-padding': 5 } }
    ];

    /** One line of short keys under the map, groups set apart by a thin rule; the panel's guide says the rest. */
    function legendHtml(state) {
        const items = [];
        const swatch = (color, label) => '<li><span class="quality-swatch" style="background:' + color + '" aria-hidden="true"></span>' + label + '</li>';
        const line = (kind, label) => '<li><span class="quality-line quality-line--' + kind + '" aria-hidden="true"></span>' + label + '</li>';
        const key = (kind, label) => '<li><span class="quality-key quality-key--' + kind + '" aria-hidden="true"></span>' + label + '</li>';
        const rule = '<li class="quality-legend__rule" aria-hidden="true"></li>';
        if (state.colorBy === 'criticality') {
            Object.keys(CRITICALITY).forEach((level) => items.push('<li>' + criticalityBadge(level) + '</li>'));
        } else if (state.colorBy === 'coverage') {
            items.push('<li><span class="quality-ramp" style="background:linear-gradient(90deg,' + COVERAGE_RAMP.join(',') + ')" aria-hidden="true"></span>Branch coverage 0–100%</li>');
            items.push(swatch(NOT_MEASURED_COLOR, 'Not measured'));
        } else if (state.colorBy === 'repository') {
            Object.keys(REPOSITORIES).forEach((repository) => items.push(swatch(REPOSITORIES[repository].color, REPOSITORIES[repository].label)));
        } else {
            items.push('<li>Colour: module, as in the list</li>');
        }
        items.push(rule);
        if (state.level === 'modules') {
            items.push(line('declared', 'Declared dependency'));
            items.push(line('undeclared', 'Undeclared dependency'));
            items.push(line('unused', 'Declared, no code reference'));
            items.push('<li><span class="quality-swatch quality-swatch--contract" aria-hidden="true"></span>Contract between repositories</li>');
            items.push(rule);
            items.push('<li>Circle size: lines of code</li>');
            return items.join('');
        }
        items.push(key('region', state.level === 'symbols' && state.module ? 'Circle: a file' : 'Circle: a module'));
        items.push('<li>Selected:</li>');
        items.push(line('declared', 'same module'));
        items.push(line('crossing', 'declared dependency'));
        items.push(line('undeclared', 'undeclared dependency'));
        items.push(rule);
        if (state.level === 'files') {
            items.push(line('clone', 'Copied code'));
            items.push(key('ring', 'Over ' + FILE_BUDGET.toLocaleString('en') + ' lines'));
            items.push('<li><span class="quality-dots" aria-hidden="true"><span></span><span></span><span></span></span>Dot size: lines</li>');
        } else {
            items.push(key('hollow', 'Nothing mentions it'));
            items.push('<li><span class="quality-dots" aria-hidden="true"><span></span><span></span><span></span></span>Dot size: how many use it</li>');
        }
        return items.join('');
    }

    function sourceLink(data, fileId, line) {
        const base = (data.source_urls || {})[repositoryOf(fileId)];
        const label = pathOf(fileId) + (line ? ':' + line : '');
        if (!base) return '<code>' + escapeHtml(label) + '</code>';
        return '<a href="' + escapeHtml(base + pathOf(fileId) + (line ? '#L' + line : '')) + '" target="_blank" rel="noopener noreferrer"><code>'
            + escapeHtml(label) + '</code></a>';
    }

    function moduleButton(moduleId) {
        return '<a href="#' + escapeHtml(moduleId) + '" class="quality-link" data-select-module="' + escapeHtml(moduleId) + '">' + escapeHtml(shortName(moduleId)) + '</a>';
    }

    function linkButton(link) {
        return '<a href="#' + escapeHtml(link.source + '>' + link.target) + '" class="quality-link" data-select-link="' + escapeHtml(link.source + '>' + link.target) + '">'
            + escapeHtml(shortName(link.source)) + ' → ' + escapeHtml(shortName(link.target)) + '</a>';
    }

    /** Rows with dividers. An item is HTML, or ``[main, aside]`` to put a short value on the right. */
    function list(items, empty) {
        if (!items.length) return '<p class="quality-empty">' + empty + '</p>';
        return '<ul class="quality-rows">' + items.map((item) => '<li>' + (Array.isArray(item)
            ? '<div class="quality-rows__line"><span>' + item[0] + '</span><span>' + item[1] + '</span></div>' + (item[2] ? '<small>' + item[2] + '</small>' : '')
            : item) + '</li>').join('') + '</ul>';
    }

    // The guide's button hides the whole panel; the ⓘ Details button in the toolbar brings it back.
    const HIDE_PANEL_BUTTON = '<button type="button" class="quality-panel__close" data-hide-panel title="Hide the details panel" aria-label="Hide the details panel"><i class="fas fa-times" aria-hidden="true"></i></button>';
    const CLOSE_BUTTON = '<button type="button" class="quality-panel__close" data-clear-selection title="Close (Esc)" aria-label="Close details"><i class="fas fa-times" aria-hidden="true"></i></button>';

    function overviewHtml(state) {
        const steps = {
            modules: [
                'Each circle is a module: a group of files with one responsibility in the module catalog. Its area is its lines of code.',
                'A module sits above the modules it lists as dependencies. An arc goes from the module whose code uses another to the module it uses, so arcs run downwards, on the outer side of the column.',
                'An orange dashed arc is a dependency the catalog does not declare, and a dotted grey one is declared but used by no code. An arc that runs upwards goes against the layering and bends to the inner side.',
                'A purple diamond is a contract: the two repositories share a file format, not code.',
                'Select a module or an arc for its details. Double-click a module to see its files in the same circle.',
                'Drag to move. Zoom with the buttons or <kbd>Ctrl</kbd>/<kbd>⌘</kbd> and scroll.'
            ],
            files: [
                'The circles are the modules, where they are on <strong>Modules</strong>. Each dot is a file; a larger dot is a longer file, and a ringed one is over ' + FILE_BUDGET.toLocaleString('en') + ' lines.',
                'Thin lines join files that use each other. Select a file to light its own lines and list what it uses and what uses it.',
                'A dashed black line joins two files that hold the same block of code. Select it to see where.',
                'Colour by <strong>Branch coverage</strong> paints each file with its own coverage: grey files are not measured.',
                'Click a module in the list to light its files. Double-click a file or a circle to see its functions.'
            ],
            symbols: [
                'Each dot is a function or class. Each module is a circle; a module drawn alone has a circle for each file.',
                'A larger dot is used by more functions and files. A hollow dot has a name that nothing else in the code mentions: it is probably unused.',
                'A line joins a function to one it calls or references. Calls through objects, such as <code>self.save()</code> or <code>this.render()</code>, are not seen.',
                'Click a module in the list, or double-click its circle, to draw it alone. <kbd>Esc</kbd> or <strong>Reset</strong> shows every function again.',
                'Select a dot for its callers and callees. Search finds a function, class or file by name.'
            ]
        };
        const titles = { modules: 'How to read the modules', files: 'How to read the files', symbols: 'How to read the functions' };
        return '<p class="quality-eyebrow">Code map</p><h2 class="quality-panel__title">' + titles[state.level] + '</h2>'
            + '<ol class="quality-steps">' + steps[state.level].map((step) => '<li>' + step + '</li>').join('') + '</ol>';
    }

    function fileButton(fileId) {
        return '<a href="#' + escapeHtml(fileId) + '" class="quality-link" data-select-file="' + escapeHtml(fileId) + '">' + escapeHtml(baseName(fileId)) + '</a>';
    }

    function moduleHtml(context, moduleId, closeButton = CLOSE_BUTTON) {
        const module = context.modules[moduleId];
        const codeMap = context.data.code_map;
        const row = (context.report.modules || {})[moduleId];
        const interfaceRows = (codeMap.interface || {})[moduleId] || [];
        const declared = new Set(module.entrypoints.map((entry) => entry.symbol).filter(Boolean));
        const usedIds = new Set(interfaceRows.map((symbol) => symbol.id));
        const outgoing = context.moduleLinks.filter((link) => link.source === moduleId);
        const incoming = context.moduleLinks.filter((link) => link.target === moduleId);
        const mine = (fileId) => context.owners[fileId] === moduleId;
        const lanes = LANES.map(([lane, label]) => {
            const summary = laneSummary(row, lane);
            return '<div><dt>' + label + '</dt><dd>' + statusBadge(summary.status, summary.text)
                + (summary.detail ? '<small>' + escapeHtml(summary.detail) + '</small>' : '') + '</dd></div>';
        }).join('');
        const count = (label, value) => '<div><dt>' + label + '</dt><dd>' + value.toLocaleString('en') + '</dd></div>';
        const dependencyItem = (link, other) => [moduleButton(other),
            (link.count ? plural(link.count, 'reference') : 'no code reference')
            + (link.declared ? '' : ' · <strong class="quality-warn-text">not declared</strong>')];
        const entrypoints = module.entrypoints.map((entry) => ['<code>' + escapeHtml(entry.entry) + '</code>', '',
            !entry.symbol ? 'Not found in the code' : usedIds.has(entry.symbol) ? 'Used from other modules' : 'Not referenced by another module\'s code']);
        const used = interfaceRows.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code>'
            + (declared.has(symbol.id) ? ' <span class="quality-tag">declared entry point</span>' : '')
            + (/^_[^_]/.test(symbol.name) ? ' <span class="quality-tag quality-tag--warn">private name</span>' : '')
            + '<small>' + sourceLink(context.data, symbol.file, symbol.line) + ' · used by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', ') + '</small>');
        const docs = Object.keys(module.docs || {}).map((kind) => module.docs[kind].map((path) => escapeHtml(kind) + ': ' + sourceLink(context.data, module.repository + ':' + path)).join('<br>'));
        const level = (id, icon, label) => (context.state.level === id ? '' : '<button type="button" class="quality-button" data-go-level="' + id
            + '" data-go-module="' + escapeHtml(moduleId) + '"><i class="fas ' + icon + '" aria-hidden="true"></i> ' + label + '</button>');
        return closeButton
            + '<p class="quality-eyebrow">' + escapeHtml((REPOSITORIES[module.repository] || {}).label || module.repository) + ' module</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(module.title) + '</h2>'
            + '<div class="quality-panel__meta"><code>' + escapeHtml(module.id) + '</code>' + criticalityBadge(module.criticality) + '</div>'
            + '<p>' + escapeHtml(module.responsibility) + '</p>'
            + '<p class="quality-muted">' + escapeHtml((CRITICALITY[module.criticality] || {}).meaning || '') + '</p>'
            + '<p class="quality-actions">' + level('files', 'fa-file-code', 'Its files') + level('symbols', 'fa-code', 'Its functions') + '</p>'
            + (row ? '<h3 class="quality-panel__subtitle">CI results</h3><dl class="quality-kv">' + lanes + '</dl>' : '')
            + '<h3 class="quality-panel__subtitle">To clean up</h3><dl class="quality-kv">'
            + count('Functions nothing mentions', context.tidy.unused.filter((symbol) => mine(symbol.file)).length)
            + count('Copied blocks', context.tidy.clones.filter((clone) => clone.files.some(mine)).length)
            + count('Files over ' + FILE_BUDGET.toLocaleString('en') + ' lines', context.tidy.large.filter((file) => mine(file.id)).length) + '</dl>'
            + '<h3 class="quality-panel__subtitle">Depends on</h3>' + list(outgoing.map((link) => dependencyItem(link, link.target)), 'Nothing.')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(incoming.map((link) => dependencyItem(link, link.source)), 'No other module.')
            + '<h3 class="quality-panel__subtitle">Declared entry points</h3>' + list(entrypoints, 'None declared.')
            + '<h3 class="quality-panel__subtitle">Used from other modules (' + interfaceRows.length + ')</h3>'
            + list(used, 'No function or class is referenced from another module\'s code. Use may go through the database or a URL built at runtime, which the map does not see.')
            + '<h3 class="quality-panel__subtitle">Invariants</h3>' + list(module.invariants.map(escapeHtml), 'None recorded.')
            + '<h3 class="quality-panel__subtitle">Documentation</h3>' + list(docs, 'None declared.')
            + '<p class="quality-panel__note">Owner: ' + escapeHtml(module.owner) + '. Catalog entry reviewed ' + escapeHtml(module.reviewed) + '.</p>';
    }

    function moduleLinkHtml(context, link) {
        const symbols = ((context.data.code_map.interface || {})[link.target] || []).filter((symbol) => symbol.used_by.includes(link.source));
        const files = {};
        link.links.forEach((item) => {
            const key = item.source + '>' + item.target;
            const entry = files[key] || (files[key] = { source: item.source, target: item.target, kinds: {} });
            addCount(entry.kinds, item.kind, item.count);
        });
        const status = link.count === 0
            ? 'The catalog declares this dependency, but no code reference was found. It may go through the database or a URL built at runtime, which the map does not see, or the declaration is out of date.'
            : link.declared ? 'The catalog declares this dependency.'
                : '<strong class="quality-warn-text">The catalog does not declare this dependency.</strong> Either declare it in <code>quality/modules.yml</code> or remove the reference.';
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">Module dependency</p>'
            + '<h2 class="quality-panel__title">' + moduleButton(link.source) + ' → ' + moduleButton(link.target) + '</h2>'
            + '<p>' + status + '</p>'
            + (link.count ? '<p class="quality-muted">' + plural(link.count, 'code reference') + ': ' + escapeHtml(kindsText(link.kinds)) + '.</p>' : '')
            + '<h3 class="quality-panel__subtitle">Names used (' + symbols.length + ')</h3>'
            + list(symbols.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code><small>' + sourceLink(context.data, symbol.file, symbol.line) + '</small>'), 'Only whole modules or files are referenced.')
            + '<h3 class="quality-panel__subtitle">Files</h3>'
            + list(Object.values(files).map((item) => sourceLink(context.data, item.source) + ' → ' + sourceLink(context.data, item.target)
                + '<small>' + escapeHtml(kindsText(item.kinds)) + '</small>'), 'None.');
    }

    /** Several modules in focus: what they are and every dependency between them, the lines the map keeps lit. */
    function modulesHtml(context, moduleIds) {
        const chosen = new Set(moduleIds);
        const between = context.moduleLinks.filter((link) => chosen.has(link.source) && chosen.has(link.target));
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">' + moduleIds.length + ' modules</p>'
            + '<h2 class="quality-panel__title">' + moduleIds.map(moduleButton).join(' + ') + '</h2>'
            + '<p class="quality-muted">The map keeps these modules and lights the lines that go from one to another. The others fade.</p>'
            + '<h3 class="quality-panel__subtitle">Dependencies between them (' + between.length + ')</h3>'
            + list(between.map((link) => [linkButton(link), link.count ? plural(link.count, 'reference') : 'declared only',
                link.declared ? '' : 'Not declared in the catalog']), 'No code of one refers to code of another.');
    }

    function fileHtml(context, fileId) {
        const codeMap = context.data.code_map;
        const file = context.files[fileId];
        const owners = context.owners;
        const ends = (links, end) => links.map((link) => fileButton(link[end]) + (owners[link[end]] !== file.module ? ' <span class="quality-tag">' + escapeHtml(shortName(owners[link[end]])) + '</span>' : '')
            + '<small>' + escapeHtml(kindsText(link.kinds)) + '</small>');
        const graph = fileGraph(codeMap, file.module);
        const used = ((codeMap.interface || {})[file.module] || []).filter((symbol) => symbol.file === fileId);
        const routes = (codeMap.routes || []).filter((route) => route.file === fileId);
        const pageLinks = {};
        codeMap.links.filter((link) => !drawn(link) && link.source === fileId).forEach((link) => addCount(pageLinks, link.target, link.count));
        const coverage = (context.report.files || {})[fileId];
        const copies = (codeMap.clones || []).map((clone, index) => ({ clone, index })).filter(({ clone }) => clone.files.includes(fileId));
        const reached = (route) => [route.requested_by.length ? 'requested by ' + route.requested_by.map(baseName).map(escapeHtml).join(', ') : '',
            route.linked_by.length ? 'linked from ' + route.linked_by.map(baseName).map(escapeHtml).join(', ') : ''].filter(Boolean).join('; ')
            || 'Nothing in the code reaches it';
        const facts = [plural(file.lines || 0, 'line'), plural(file.symbols || 0, 'function or class', 'functions and classes')];
        if (coverageOf(coverage) !== null) {
            facts.push(typeof coverage.branches === 'number' ? coverage.branches + '% branch coverage' : 'no branches');
            if (typeof coverage.lines === 'number') facts.push(coverage.lines + '% of lines covered');
        }
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">File in ' + escapeHtml(shortName(file.module)) + '</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(baseName(fileId)) + '</h2>'
            + '<p>' + sourceLink(context.data, fileId) + '</p>'
            + '<p class="quality-muted">' + facts.join(', ') + '.</p>'
            + (file.symbols && context.state.level !== 'symbols' ? '<p class="quality-actions"><button type="button" class="quality-button" data-show-functions="' + escapeHtml(fileId)
                + '"><i class="fas fa-code" aria-hidden="true"></i> Its functions</button></p>' : '')
            + '<h3 class="quality-panel__subtitle">Used from other modules (' + used.length + ')</h3>'
            + list(used.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code><small>by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', ') + '</small>'), 'Nothing in this file.')
            + (routes.length ? '<h3 class="quality-panel__subtitle">Routes (' + routes.length + ')</h3>'
                + list(routes.map((route) => ['<code>' + escapeHtml(route.pattern) + '</code>', escapeHtml(route.methods.join(', ')), reached(route)]), '') : '')
            + '<h3 class="quality-panel__subtitle">Uses</h3>' + list(ends(graph.links.filter((link) => link.source === fileId), 'target'), 'No other file.')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(ends(graph.links.filter((link) => link.target === fileId), 'source'), 'No other file.')
            + (copies.length ? '<h3 class="quality-panel__subtitle">Copied code (' + copies.length + ')</h3>' + list(copies.map(({ clone, index }) => {
                const here = clone.locations.find((location) => location.file === fileId);
                const other = clone.locations.find((location) => location !== here);
                return ['<a href="#clone" class="quality-link" data-select-clone="' + index + '">Lines ' + here.start + '–' + here.end + '</a>', plural(clone.lines, 'line'),
                    'also in ' + sourceLink(context.data, other.file, other.start)];
            }), '') : '')
            + (Object.keys(pageLinks).length ? '<h3 class="quality-panel__subtitle">Links to pages</h3>'
                + list(Object.keys(pageLinks).sort().map((target) => [fileButton(target), plural(pageLinks[target], 'link')]), '') : '');
    }

    /** A function's callers and callees, each a link that selects it on the Functions level. */
    function functionHtml(context, symbolId) {
        const codeMap = context.data.code_map;
        const symbol = context.symbols[symbolId];
        const moduleId = context.owners[symbol.file];
        const route = (codeMap.routes || []).find((item) => item.symbol === symbolId);
        const usedBy = ((codeMap.interface || {})[moduleId] || []).find((item) => item.id === symbolId);
        const links = (codeMap.symbol_links || []).filter((link) => link.source === symbolId || link.target === symbolId);
        const end = (id) => {
            const other = context.symbols[id];
            const file = other ? other.file : id;
            const tag = context.owners[file] !== moduleId ? ' <span class="quality-tag">' + escapeHtml(shortName(context.owners[file] || '')) + '</span>' : '';
            const name = other
                ? '<a href="#' + escapeHtml(id) + '" class="quality-link" data-select-function="' + escapeHtml(id) + '"><code>' + escapeHtml(other.name) + '</code></a>'
                : fileButton(id) + ' (file level)';
            return name + tag + '<small>' + sourceLink(context.data, file, other ? other.line : null) + '</small>';
        };
        const rows = (side, other) => links.filter((link) => link[side] === symbolId)
            .sort((a, b) => a[other].localeCompare(b[other]) || a.kind.localeCompare(b.kind))
            .map((link) => [end(link[other]), escapeHtml(kindsText({ [link.kind]: link.count }))]);
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">Function in ' + escapeHtml(baseName(symbol.file)) + '</p>'
            + '<h2 class="quality-panel__title"><code>' + escapeHtml(symbol.name) + '</code></h2>'
            + '<p>' + sourceLink(context.data, symbol.file, symbol.line) + '</p>'
            + '<p class="quality-muted">In ' + fileButton(symbol.file) + ', module ' + moduleButton(moduleId) + '.</p>'
            + (symbol.unused ? '<p class="quality-callout">Nothing else in the code of either repository mentions this name, tests aside. It is probably unused: check for a call the map cannot see before deleting it.</p>' : '')
            + (route ? '<p>Answers <code>' + escapeHtml(route.methods.join(', ') + ' ' + route.pattern) + '</code>.</p>' : '')
            + (usedBy ? '<p class="quality-muted">Used from ' + usedBy.used_by.map(shortName).map(escapeHtml).join(', ') + '.</p>' : '')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(rows('target', 'source'), 'Nothing the map can see.')
            + '<h3 class="quality-panel__subtitle">Uses</h3>' + list(rows('source', 'target'), 'Nothing the map can see.');
    }

    /** One pair of copied blocks: where each copy is. */
    function cloneHtml(context, index) {
        const clone = context.data.code_map.clones[index];
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">Copied code</p>'
            + '<h2 class="quality-panel__title">' + plural(clone.lines, 'line') + ' found twice</h2>'
            + '<p>The same block of code is in both places. One shared function would leave a single copy to change.</p>'
            + list(clone.locations.map((location) => [fileButton(location.file) + ' <span class="quality-tag">' + escapeHtml(shortName(context.owners[location.file] || '')) + '</span>',
                'lines ' + location.start + '–' + location.end, sourceLink(context.data, location.file, location.start)]), '');
    }

    function contractHtml(context, contractId) {
        const contract = (context.data.code_map.contracts || []).find((item) => 'contract:' + item.id === contractId);
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">Contract</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(contract.title) + '</h2>'
            + '<p><code>' + escapeHtml(contract.id) + '</code></p>'
            + '<p>The repositories do not import each other. They agree on this versioned format instead, and contract tests check both sides.</p>'
            + '<h3 class="quality-panel__subtitle">Produced by</h3>' + list(contract.producers.map(moduleButton), 'Nobody.')
            + '<h3 class="quality-panel__subtitle">Consumed by</h3>' + list(contract.consumers.map(moduleButton), 'Nobody.');
    }

    /**
     * Findings as cards, each a titled list with its count; ``warn`` marks a list as something to act on. A card shows
     * FINDING_ROWS rows and folds the rest away. The groups that found nothing share one card of one line each, so an
     * empty check never takes a card of its own.
     */
    function findingGroups(groups) {
        const card = ({ title, lead, items, warn = true }) => '<div class="quality-finding' + (warn ? ' quality-finding--warn' : '') + '">'
            + '<div class="quality-finding__head"><h3>' + title + '</h3><span class="quality-finding__count">' + items.length + '</span></div>'
            + '<p>' + lead + '</p>' + list(items.slice(0, FINDING_ROWS))
            + (items.length > FINDING_ROWS ? '<details class="quality-more"><summary>Show ' + (items.length - FINDING_ROWS) + ' more</summary>'
                + list(items.slice(FINDING_ROWS)) + '</details>' : '') + '</div>';
        const clear = groups.filter((group) => !group.items.length);
        return groups.filter((group) => group.items.length).map(card).join('')
            + (clear.length ? '<ul class="quality-clear">' + clear.map((group) => '<li><i class="fas fa-check" aria-hidden="true"></i>'
                + '<span><strong>' + group.title + ':</strong> none. <small>' + group.lead + '</small></span></li>').join('') + '</ul>' : '');
    }

    function findingsHtml(context) {
        const findings = context.findings;
        const privateItems = findings.privateNames.map((symbol) => ['<code>' + escapeHtml(symbol.name) + '</code> in ' + moduleButton(symbol.module),
            'used by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', '), sourceLink(context.data, symbol.file, symbol.line)]);
        return findingGroups([
            { title: 'Undeclared module dependencies', lead: 'Code in one module references another module the catalog does not list as a dependency.',
                items: findings.undeclared.map((link) => [linkButton(link), plural(link.count, 'reference')]) },
            { title: 'Modules that depend on each other', lead: 'Each of the two modules references the other, so neither can change in isolation.',
                items: findings.cycles.map((link) => moduleButton(link.source) + ' ⇄ ' + moduleButton(link.target)) },
            { title: 'Private names used across a boundary', lead: 'A name starting with <code>_</code> is internal to its module, but another module uses it.', items: privateItems },
            { title: 'Declared dependencies without code references', lead: 'These may go through the database or a URL built at runtime, which the map does not see, or the declaration is out of date.',
                items: findings.unused.map(linkButton) }
        ]);
    }

    function blindSpotsHtml(context) {
        const data = context.data;
        const spots = blindSpots(data.code_map);
        const at = (row) => sourceLink(data, row.file, row.line);
        return findingGroups([
            { title: 'References that reach nothing', lead: 'A URL, <code>url_for</code> endpoint or template name in the code that the app does not serve: a typo, a route that was removed, or a URL with a part the map could not follow.',
                items: spots.unmatched.map((row) => ['<code>' + escapeHtml(row.reference) + '</code>', escapeHtml(UNMATCHED_KINDS[row.kind] || row.kind), at(row)]) },
            { title: 'Routes nothing in the code reaches', lead: 'No script, template or view requests or links to these. They may serve outside clients, crawlers or links in the documentation, be reached through a URL built at runtime, or be unused.',
                items: spots.unreached.map((route) => ['<code>' + escapeHtml(route.pattern) + '</code>', escapeHtml(route.methods.join(', ')), sourceLink(data, route.file, route.line)]), warn: false },
            { title: 'URLs and templates chosen at runtime', lead: 'Here the code passes a variable, not a fixed text, to a request, <code>url_for</code> or <code>render_template</code>, so the map draws no arrow from this line. This is expected and not a defect: it only means an arrow may be missing.',
                items: spots.dynamic.map((row) => ['<code>' + escapeHtml(row.expression) + '</code>', escapeHtml(DYNAMIC_KINDS[row.kind] || row.kind), at(row)]), warn: false },
            { title: 'Browser names declared by several scripts', lead: 'Scripts share one global scope, so a reference to one of these names cannot be linked to one script; on a page loading several, the last one wins.',
                items: spots.sharedNames.map((row) => ['<code>' + escapeHtml(row.name) + '</code>', plural(row.symbols.length, 'script'),
                    row.symbols.map((symbol) => sourceLink(data, symbolFile(symbol), symbolLine(symbol))).join('<br>')]) },
            { title: 'Limits of the method', lead: 'What reading the code cannot establish, whatever the code looks like.',
                items: (data.code_map.limitations || []).map(escapeHtml), warn: false }
        ]);
    }

    function cleanupHtml(context) {
        const data = context.data;
        const tidy = context.tidy;
        const module = (fileId) => ' <span class="quality-tag">' + escapeHtml(shortName(context.owners[fileId] || '')) + '</span>';
        return findingGroups([
            { title: 'Functions nothing mentions', warn: false,
                lead: 'The name of the function or class appears nowhere else in the code of either repository, tests aside. Probably unused: check for a call the map cannot see before deleting.',
                items: tidy.unused.map((symbol) => ['<a href="#' + escapeHtml(symbol.id) + '" class="quality-link" data-select-function="' + escapeHtml(symbol.id) + '"><code>'
                    + escapeHtml(symbol.name) + '</code></a>' + module(symbol.file), '', sourceLink(data, symbol.file, symbol.line)]) },
            { title: 'Copied code', warn: false, lead: 'The same block of at least 10 lines in two places. The largest come first.',
                items: tidy.clones.map((clone, index) => ({ clone, index })).sort((a, b) => b.clone.lines - a.clone.lines).map(({ clone, index }) => [
                    '<a href="#clone" class="quality-link" data-select-clone="' + index + '">' + clone.files.map(baseName).map(escapeHtml).join(' ⇄ ') + '</a>', plural(clone.lines, 'line'),
                    clone.locations.map((location) => sourceLink(data, location.file, location.start)).join('<br>')]) },
            { title: 'Files over ' + FILE_BUDGET.toLocaleString('en') + ' lines', warn: false, lead: 'Long files are hard to review and are where copies hide. Generated and data files are not counted.',
                items: tidy.large.map((file) => [fileButton(file.id) + module(file.id), file.lines.toLocaleString('en') + ' lines', sourceLink(data, file.id)]) }
        ]);
    }

    function figuresHtml(context) {
        const codeMap = context.data.code_map;
        const findings = context.findings;
        const figure = (value, label, target, warn) => '<a class="quality-figure' + (warn && value ? ' quality-figure--warn' : '') + '" href="#' + target + '">'
            + '<strong class="quality-figure__value">' + value.toLocaleString('en') + '</strong><span class="quality-figure__label">' + label + '</span></a>';
        return figure(codeMap.modules.length, 'Modules', 'qualityMapTitle')
            + figure(codeMap.files.length, 'Files', 'qualityMapTitle')
            + figure((codeMap.symbols || []).length, 'Functions and classes', 'qualityMapTitle')
            + figure(findings.undeclared.length + findings.cycles.length + findings.privateNames.length + findings.unused.length, 'Boundary findings', 'qualityFindingsTitle', true)
            + figure(context.tidy.unused.length, 'Functions nothing mentions', 'qualityCleanupTitle')
            + figure(context.tidy.clones.length, 'Copied blocks', 'qualityCleanupTitle')
            + figure(context.tidy.large.length, 'Files over ' + FILE_BUDGET.toLocaleString('en') + ' lines', 'qualityCleanupTitle');
    }

    /** The CI results of every module: one row each, with a bar under its branch coverage. */
    function tableHtml(context) {
        const report = context.report;
        const head = '<thead><tr><th scope="col">Module</th><th scope="col">Criticality</th>' + LANES.map(([, label]) => '<th scope="col">' + label + '</th>').join('') + '</tr></thead>';
        return head + '<tbody>' + Object.keys(report.modules || {}).sort().map((moduleId) => {
            const row = report.modules[moduleId];
            const module = context.modules[moduleId];
            const cells = LANES.map(([lane]) => {
                const summary = laneSummary(row, lane);
                const share = lane === 'coverage' ? coverageOf(row.coverage) : null;
                return '<td>' + statusBadge(summary.status, summary.text)
                    + (share === null ? '' : '<span class="quality-meter" aria-hidden="true"><span style="width:' + share + '%"></span></span>') + '</td>';
            }).join('');
            return '<tr><th scope="row">' + (module ? moduleButton(moduleId)
                + '<span class="quality-table__repo">' + escapeHtml((REPOSITORIES[module.repository] || {}).label || module.repository) + '</span>' : escapeHtml(moduleId))
                + '</th><td>' + criticalityBadge(row.criticality) + '</td>' + cells + '</tr>';
        }).join('') + '</tbody>';
    }

    /** The pill beside the results: failed checks first, then whether every measurement is there. */
    function runStatus(report) {
        if ((report.checks || []).some((check) => check.status === 'fail')) return { tone: 'bad', label: 'Checks failed' };
        if (report.completeness === 'complete') return { tone: 'good', label: 'Complete' };
        return { tone: 'warn', label: report.completeness ? report.completeness.charAt(0).toUpperCase() + report.completeness.slice(1) : 'Unknown' };
    }

    function summaryHtml(data) {
        const report = data.report;
        const revision = report.revision || {};
        const checks = report.checks || [];
        const passed = checks.filter((check) => check.status === 'pass').length;
        const generated = report.generated_at ? new Date(report.generated_at) : null;
        const item = (label, value) => '<div class="quality-run__fact"><dt>' + label + '</dt><dd>' + value + '</dd></div>';
        const commit = (repository) => {
            const sha = revision[repository];
            const base = (data.source_urls || {})[repository];
            if (!sha) return 'unknown';
            const label = '<code>' + escapeHtml(sha.slice(0, 7)) + '</code>';
            return base ? '<a href="' + escapeHtml(base.replace(/\/blob\/[^/]+\/$/, '/commit/' + sha)) + '" target="_blank" rel="noopener noreferrer">' + label + '</a>' : label;
        };
        return item('Required checks', !checks.length ? statusBadge('not_measured')
            : statusBadge(passed === checks.length ? 'pass' : 'fail', passed + ' of ' + checks.length + ' passed'))
            + item('App commit', commit('app'))
            + item('Engine commit', commit('engine'))
            + item('Measured', generated && !isNaN(generated) ? escapeHtml(generated.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })) : 'unknown')
            + (data.run_url ? item('Checks on GitHub', '<a href="' + escapeHtml(data.run_url) + '" target="_blank" rel="noopener noreferrer">CI run <i class="fas fa-external-link-alt" aria-hidden="true"></i></a>') : '');
    }

    function checksHtml(report) {
        const checks = report.checks || [];
        if (!checks.length) return '<p class="quality-empty">No check results recorded.</p>';
        return '<ul class="quality-checks">' + checks.map((check) => '<li><code>' + escapeHtml(check.name) + '</code>' + statusBadge(check.status) + '</li>').join('') + '</ul>';
    }

    /** Why there is nothing to show, in the words of the page. */
    function unavailableHtml(data) {
        const commit = data && data.revision ? ' <code>' + escapeHtml(String(data.revision).slice(0, 7)) + '</code>' : '';
        if (data && data.reason === 'unknown_commit') {
            return '<strong>This server does not know which commit it runs.</strong> It finds the CI results by commit, from a Git checkout or a <code>REVISION</code> file.';
        }
        if (data && data.reason === 'no_results') {
            return '<strong>No CI results for commit' + commit + ' yet.</strong> They appear here a few minutes after the checks finish on GitHub. Missing results are not a passing result.';
        }
        return '<strong>The code quality data could not be loaded.</strong> Missing results are not a passing result.';
    }

    function createContext(data, state) {
        const codeMap = data.code_map;
        const moduleLinks = aggregateModuleLinks(codeMap);
        const graph = symbolGraph(codeMap);
        return {
            data, moduleLinks, state,
            report: data.report || {},
            modules: indexBy(codeMap.modules, 'id'),
            files: indexBy(codeMap.files, 'id'),
            symbols: indexBy(codeMap.symbols || [], 'id'),
            owners: fileOwners(codeMap),
            findings: boundaryFindings(codeMap, moduleLinks),
            tidy: cleanup(codeMap),
            colors: moduleColors(codeMap),
            symbolGraph: graph,
            symbolNodes: indexBy(graph.nodes, 'id'),
            views: {}
        };
    }

    function init(root) {
        const element = (selector) => root.querySelector(selector);
        // The level drawn, the module in focus on it (selected on Modules, its files lit on Files, drawn alone on
        // Functions), the colour encoding and the Edges and Labels switches. The focus survives a change of level.
        const state = { level: 'modules', module: null, modules: [], colorBy: 'module', showEdges: true, showLabels: true, expanded: false, panelOpen: true };
        const mapElement = element('#qualityMap');
        const search = element('#qualitySearch');
        const searchResults = element('#qualitySearchResults');
        let context = null;
        let cy = null;
        let hintTimer = null;
        let tooltipTimer = null;
        let tooltipShown = false;
        let matches = [];
        let activeMatch = -1;
        // The dots named around a selection, as ids and the selected dot, and the zoom the names were placed at.
        let named = null;
        let namedZoom = null;

        function setPanel(html) {
            element('#qualityPanel').innerHTML = html;
            element('#qualityPanel').scrollTop = 0;
        }

        function selected() {
            return cy ? cy.$(':selected') : null;
        }

        function view() {
            return mapView(context, state.level, state.module);
        }

        /** Space around the map when it is fitted. The cloud of every function is round and can go closer to the edges. */
        function fitPadding() {
            return state.level === 'symbols' && !state.module ? 24 : 56;
        }

        /**
         * Fades everything but ``target`` and its direct neighbours, lights their lines and names the dots that stay.
         * With ``alone``, only the other dots fade: the lines stay faint and names show by zoom, as for the files of
         * a module in focus. The circles stay, so a selection is still seen in its module or file.
         */
        function highlight(target, alone) {
            const some = target && target.length;
            const keep = !some ? null : alone ? target : target.isNode() ? target.closedNeighborhood() : target.connectedNodes().union(target);
            cy.batch(() => {
                cy.elements().removeClass('faded lit named');
                if (keep) cy.elements(alone ? '.dot' : '*').not(keep).not('.region, .region-label').addClass('faded');
                if (keep && !alone) keep.edges().addClass('lit');
            });
            named = keep && !alone && state.level !== 'modules' ? { ids: new Set(keep.nodes().map((node) => node.id())), first: target.length === 1 ? target.id() : null } : null;
            nameDots();
        }

        function setModules(moduleIds) {
            state.modules = [].concat(moduleIds || []);
            state.module = state.modules.length === 1 ? state.modules[0] : null;
        }

        /** What the modules in focus cover on the map: their circles on Files, their dots among every function. */
        function focusArea() {
            const chosen = new Set(state.modules);
            if (state.level === 'files' && chosen.size) return cy.nodes('.region').filter((node) => chosen.has(node.data('region')));
            if (state.level === 'symbols' && chosen.size > 1) return cy.nodes('.dot').filter((node) => chosen.has(node.data('module')));
            return null;
        }

        /**
         * The modules in focus stay and every other module fades, also the ones they depend on. The lines lit are those
         * of a single module on Modules, where they are its dependencies, and with several modules the lines from one
         * of them to another. The files of a single module keep their lines faint: there are hundreds.
         */
        function highlightModules() {
            const chosen = new Set(state.modules);
            const single = chosen.size === 1;
            const moduleOf = (node) => (node.data('kind') === 'module' ? node.id() : node.data('module'));
            const end = (edge, side) => cy.getElementById(edge.data(side));
            cy.batch(() => {
                cy.elements().removeClass('faded lit named');
                cy.nodes('.module, .dot').forEach((node) => {
                    if (!chosen.has(moduleOf(node))) node.addClass('faded');
                });
                cy.edges().forEach((edge) => {
                    const source = moduleOf(end(edge, 'source'));
                    const target = moduleOf(end(edge, 'target'));
                    // A contract hangs on the modules it joins: its line counts when the module at its other end is in focus.
                    const contract = edge.data('kind') === 'contract-link';
                    const between = single ? state.level === 'modules' && (chosen.has(source) || chosen.has(target))
                        : !contract && source !== target && chosen.has(source) && chosen.has(target);
                    if (between) edge.addClass('lit');
                    else if (!single || state.level === 'modules') edge.addClass('faded');
                });
                cy.nodes('.contract').forEach((node) => {
                    if (!node.connectedEdges().filter((edge) => edge.hasClass('lit')).length) node.addClass('faded');
                });
            });
            named = null;
            nameDots();
        }

        /** With nothing selected: the module in focus, selected on Modules and with its files lit on Files, or the guide. */
        function showFocus() {
            // One module drawn alone needs no fading: it is all there is.
            if (state.modules.length && !(state.level === 'symbols' && state.module)) highlightModules();
            else highlight(null);
            if (state.modules.length > 1) {
                setPanel(modulesHtml(context, state.modules));
                return;
            }
            if (state.module && state.level === 'modules') cy.getElementById(state.module).select();
            // A module drawn alone is the map itself: its × hides the panel. Elsewhere it gives up the focus.
            setPanel(state.module ? moduleHtml(context, state.module, state.level === 'symbols' ? HIDE_PANEL_BUTTON : CLOSE_BUTTON) : HIDE_PANEL_BUTTON + overviewHtml(state));
        }

        function select(target) {
            cy.elements().unselect();
            const kind = target && target.length ? target.data('kind') : null;
            if (kind === 'module') setModules(target.id());
            else if (state.level === 'modules') setModules(null);
            if (!kind || kind === 'module') {
                showFocus();
                chrome();
                return;
            }
            target.select();
            highlight(target);
            // A selection asks for its details, so a hidden panel opens again, keeping the selection in view.
            if (!state.panelOpen) {
                setPanelOpen(true);
                const box = target.renderedBoundingBox();
                if (box.x2 > cy.width()) cy.animate({ center: { eles: target } }, { duration: 200 });
            }
            const data = target.data();
            if (kind === 'module-link') setPanel(moduleLinkHtml(context, context.moduleLinks.find((link) => link.source === data.source && link.target === data.target)));
            else if (kind === 'file') setPanel(fileHtml(context, data.id));
            else if (kind === 'symbol') setPanel(functionHtml(context, data.id));
            else if (kind === 'contract') setPanel(contractHtml(context, data.id));
            else if (kind === 'clone') setPanel(cloneHtml(context, data.clone));
            chrome();
        }

        /** One step back: the selection first, then the module in focus. A module drawn alone stays unless ``leave``. */
        function clear(leave) {
            if (selected().filter((item) => item.data('kind') !== 'module').length) select(null);
            else if (state.modules.length && (state.level !== 'symbols' || leave || !state.module)) go(state.level, null);
        }

        /** Brings ``target`` into the middle of the map, for selections made outside it. */
        function reveal(target, zoom) {
            if (!target || !target.length || typeof cy.animate !== 'function') return;
            cy.animate(Object.assign({ center: { eles: target } }, zoom ? { zoom: Math.max(cy.zoom(), zoom) } : {}), { duration: 300, easing: 'ease-in-out-cubic' });
        }

        function crumbsHtml() {
            const all = LEVELS[state.level].all;
            if (!state.modules.length) return '<i class="fas fa-sitemap" aria-hidden="true"></i> ' + all;
            return '<button type="button" data-reset title="' + all + ' (Esc)"><i class="fas fa-arrow-left" aria-hidden="true"></i> ' + all + '</button>'
                + '<span class="quality-crumbs__sep" aria-hidden="true"><i class="fas fa-chevron-right"></i></span><span>' + escapeHtml(state.modules.map(shortName).join(' + ')) + '</span>';
        }

        function setPressed(selector, active) {
            root.querySelectorAll(selector).forEach((button) => {
                const on = active(button);
                button.classList.toggle('is-active', on);
                button.setAttribute('aria-pressed', String(on));
            });
        }

        /** The module list, in the order the map stacks the modules, with what the level counts. It is also the colour key. */
        function renderExplorer() {
            const codeMap = context.data.code_map;
            const counts = state.level === 'modules' ? moduleLines(codeMap) : {};
            if (state.level === 'files') codeMap.files.forEach((file) => addCount(counts, file.module, 1));
            if (state.level === 'symbols') context.symbolGraph.nodes.forEach((node) => addCount(counts, node.module, 1));
            element('#qualityExplorer').dataset.shows = state.level;
            element('#qualityExplorerUnit').textContent = LEVELS[state.level].unit;
            element('#qualityExplorerModules').innerHTML = moduleHierarchy(codeMap).map((moduleId, index, ids) => {
                    const module = context.modules[moduleId];
                    const first = index && module.repository !== context.modules[ids[index - 1]].repository;
                    const on = state.modules.includes(moduleId);
                    const pick = (on ? 'Remove ' : 'Add ') + shortName(moduleId) + (on ? ' from' : ' to') + ' the modules shown together';
                    return '<li' + (first ? ' class="quality-explorer__repository"' : '') + '><button type="button" class="quality-explorer__pick" role="checkbox" aria-checked="' + on + '" data-explorer-pick="' + escapeHtml(moduleId)
                        + '" title="' + escapeHtml(pick) + '" aria-label="' + escapeHtml(pick) + '"><i class="fas fa-check" aria-hidden="true"></i></button>'
                        + '<button type="button" class="quality-explorer__module' + (on ? ' is-active' : '') + '" data-explorer-module="' + escapeHtml(moduleId)
                        + '" aria-pressed="' + on + '" title="' + escapeHtml(module.title) + '">'
                        + '<span class="quality-swatch quality-swatch--dot" style="background:' + nodeColor(module, context.report, state.colorBy, context.colors) + '" aria-hidden="true"></span>'
                        + '<span class="quality-explorer__name">' + escapeHtml(shortName(moduleId)) + '</span>'
                        + '<span class="quality-explorer__count">' + (counts[moduleId] || 0).toLocaleString('en') + '</span></button></li>';
                }).join('');
            element('#qualityExplorerReset').disabled = !state.modules.length && !selected().length && !search.value;
        }

        /** Everything around the map that names the level, the module in focus and the colours. */
        function chrome() {
            element('#qualityLegend').innerHTML = legendHtml(state);
            element('#qualityBreadcrumb').innerHTML = crumbsHtml();
            setPressed('[data-level]', (button) => button.dataset.level === state.level);
            setPressed('[data-color-by]', (button) => button.dataset.colorBy === state.colorBy);
            renderExplorer();
        }

        /**
         * Names the circles, and the dots whose name is at least LABEL_PX tall at the current zoom and does not cover a
         * name already placed, largest dots first; around a selection, the selection and as many neighbours as fit.
         * Only what changes is restyled.
         */
        function nameDots() {
            const zoom = cy.zoom();
            namedZoom = zoom;
            const options = state.level === 'modules' ? { only: new Set() } : named ? { only: named.ids, first: named.first } : {};
            const shown = new Map(labelPlaces(view(), zoom, options).map((place) => [place.id, place]));
            cy.batch(() => cy.nodes('.dot, .region-label').forEach((node) => {
                const place = shown.get(node.id());
                const region = node.hasClass('region-label');
                const name = named && !region ? 'named' : 'labelled';
                if (place && node.data('labelFont') !== place.font) node.data('labelFont', place.font);
                if (Boolean(place) !== node.hasClass(name)) node.toggleClass(name, Boolean(place));
                if (Boolean(place && place.above) !== node.hasClass('above')) node.toggleClass('above', Boolean(place && place.above));
                if (named && !region && node.hasClass('labelled')) node.removeClass('labelled');
            }));
        }

        // While a zoom runs the names scale with the map; they are placed for the new zoom once it rests, or at once
        // when the zoom has doubled or halved since, so a long zoom never shows names more than twice their size.
        let namingTimer = null;
        function scheduleNames() {
            global.clearTimeout(namingTimer);
            if (namedZoom && Math.abs(Math.log2(cy.zoom() / namedZoom)) >= 1) nameDots();
            else namingTimer = global.setTimeout(nameDots, NAME_DELAY);
        }

        /** Applies the Edges and Labels switches to the dots and their lines. */
        function applySwitches() {
            cy.batch(() => {
                cy.edges('.dot-link').toggleClass('hidden', !state.showEdges);
                cy.nodes('.dot').toggleClass('unlabelled', !state.showLabels);
            });
        }

        function render() {
            cy.elements().remove();
            cy.add(mapElements(context, state, view()));
            cy.layout({ name: 'preset', fit: true, padding: fitPadding() }).run();
            if (state.level === 'symbols' && cy.zoom() > MODULE_MAX_ZOOM) {
                cy.zoom(MODULE_MAX_ZOOM);
                cy.center();
            }
            // On Files the module in focus fills the map: its circle is where it was on Modules.
            const area = focusArea();
            if (area && area.length) cy.fit(area, fitPadding());
            applySwitches();
            showFocus();
            chrome();
        }

        /** Re-renders behind a short fade, so switching views does not jump. */
        function switchView(after) {
            mapElement.style.transition = 'none';
            mapElement.classList.add('is-switching');
            void mapElement.offsetWidth;
            mapElement.style.transition = '';
            render();
            if (after) after();
            global.requestAnimationFrame(() => mapElement.classList.remove('is-switching'));
        }

        /** Shows ``level`` with ``moduleId`` in focus, drawing again only when the picture changes, then runs ``after``. */
        function go(level, moduleId, after) {
            const before = state.module;
            const levelChanged = level !== state.level;
            state.level = level;
            setModules(moduleId);
            // On Functions one module is drawn alone; none or several are shown among every function.
            const redraw = levelChanged || (level === 'symbols' && state.module !== before);
            if (redraw) {
                switchView(after);
                return;
            }
            cy.elements().unselect();
            showFocus();
            chrome();
            if (after) after();
        }

        /** Brings the module in focus, or the whole map, into view. */
        function frame() {
            const area = focusArea();
            cy.animate({ fit: { eles: area && area.length ? area : cy.elements(), padding: fitPadding() } }, { duration: 260, easing: 'ease-in-out-cubic' });
        }

        /** The module to draw on Functions for something in ``fileId``: its own, unless every function is already drawn. */
        function moduleFor(fileId) {
            const owner = context.owners[fileId];
            if (state.level !== 'symbols' || state.module) return owner;
            return state.modules.includes(owner) ? state.modules : null;
        }

        function showSymbol(symbolId) {
            const symbol = context.symbols[symbolId];
            if (!symbol) return;
            go('symbols', moduleFor(symbol.file), () => {
                select(cy.getElementById(symbolId));
                reveal(cy.getElementById(symbolId), FOCUS_ZOOM);
            });
        }

        function showFile(fileId) {
            go('files', null, () => {
                select(cy.getElementById(fileId));
                reveal(cy.getElementById(fileId), FOCUS_ZOOM);
            });
        }

        /** On Functions: selects every function of one file, fitted to the map, with the file in the panel. */
        function showFunctionsOf(fileId) {
            go('symbols', moduleFor(fileId), () => {
                const dots = cy.nodes('.dot').filter((dot) => dot.data('file') === fileId);
                cy.elements().unselect();
                dots.select();
                highlight(dots);
                setPanel(fileHtml(context, fileId));
                if (dots.length) cy.animate({ fit: { eles: dots.closedNeighborhood(), padding: 60 } }, { duration: 300, easing: 'ease-in-out-cubic' });
                renderExplorer();
            });
        }

        /** Selects an arc of the Modules level or a pair of copied blocks of the Files level, by its element id. */
        function showEdge(level, id) {
            go(level, null, () => {
                select(cy.getElementById(id));
                reveal(cy.getElementById(id));
            });
        }

        function zoomBy(factor) {
            if (!cy) return;
            const extent = cy.extent();
            const zoomLevel = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * factor));
            cy.animate({ zoom: { level: zoomLevel, position: { x: (extent.x1 + extent.x2) / 2, y: (extent.y1 + extent.y2) / 2 } } }, { duration: 180 });
        }

        function flashHint() {
            const hint = element('#qualityZoomHint');
            hint.classList.add('is-visible');
            global.clearTimeout(hintTimer);
            hintTimer = global.setTimeout(() => hint.classList.remove('is-visible'), 1400);
        }

        function hideTooltip() {
            global.clearTimeout(tooltipTimer);
            element('#qualityTooltip').hidden = true;
            tooltipShown = false;
        }

        /** Shows ``target``'s tooltip beside it, not at the cursor, so it stays put while the cursor moves. */
        function showTooltip(target) {
            const box = element('#qualityTooltip');
            const html = target.removed() ? '' : tooltipHtml(target);
            if (!html) {
                hideTooltip();
                return;
            }
            box.innerHTML = html;
            box.hidden = false;
            tooltipShown = true;
            const width = box.offsetWidth;
            const height = box.offsetHeight;
            const gap = 10;
            let x;
            let y;
            if (target.isNode()) {
                const bounds = target.renderedBoundingBox({ includeLabels: false, includeOverlays: false });
                x = bounds.x2 + gap + width > mapElement.clientWidth ? bounds.x1 - gap - width : bounds.x2 + gap;
                y = bounds.y1;
            } else {
                const middle = target.renderedMidpoint();
                x = middle.x + gap + width > mapElement.clientWidth ? middle.x - gap - width : middle.x + gap;
                y = middle.y + gap;
            }
            box.style.left = Math.round(Math.max(8, x)) + 'px';
            box.style.top = Math.round(Math.max(8, Math.min(y, mapElement.clientHeight - height - 8))) + 'px';
        }

        /** Hover only marks: the element and its own arrows. Its tooltip follows once the cursor rests on it. */
        function hoverStart(target) {
            cy.elements('.hover').removeClass('hover');
            target.addClass('hover');
            if (target.isNode()) target.connectedEdges().addClass('hover');
            global.clearTimeout(tooltipTimer);
            // While a tooltip is showing, moving straight to a neighbour shows the neighbour's at once. A circle is crossed
            // on the way between its dots, so its own tooltip always waits for the cursor to rest.
            if (tooltipShown && target.data('kind') !== 'region') showTooltip(target);
            else tooltipTimer = global.setTimeout(() => showTooltip(target), HOVER_DELAY);
        }

        function hoverEnd() {
            cy.elements('.hover').removeClass('hover');
            global.clearTimeout(tooltipTimer);
            tooltipTimer = global.setTimeout(hideTooltip, TOOLTIP_GRACE);
        }

        function tooltipHtml(target) {
            const data = target.data();
            const report = context.report;
            const count = (number) => plural(number, 'function or class', 'functions and classes');
            if (data.kind === 'module' || (data.kind === 'region' && data.of === 'module')) {
                const module = context.modules[data.kind === 'module' ? data.id : data.region];
                const coverage = laneSummary((report.modules || {})[module.id], 'coverage');
                return '<strong>' + escapeHtml(shortName(module.id)) + '</strong><span>' + escapeHtml(module.title) + '<br>' + escapeHtml(module.criticality) + ' criticality · branch coverage '
                    + escapeHtml(coverage.text.toLowerCase()) + ' · ' + plural(moduleLines(context.data.code_map)[module.id] || 0, 'line')
                    + '<br>Double-click for its ' + (state.level === 'modules' ? 'files' : 'functions') + '</span>';
            }
            if (data.kind === 'region') {
                return '<strong>' + escapeHtml(baseName(data.region)) + '</strong><span>' + escapeHtml(pathOf(data.region)) + ' · ' + count(data.count) + '</span>';
            }
            if (data.kind === 'module-link') {
                const link = context.moduleLinks.find((item) => item.source === data.source && item.target === data.target);
                return '<strong>' + escapeHtml(shortName(link.source)) + ' → ' + escapeHtml(shortName(link.target)) + '</strong><span>'
                    + (link.count ? escapeHtml(kindsText(link.kinds)) : 'No code reference found') + (link.declared ? '' : '<br>Not declared in the catalog') + '</span>';
            }
            if (data.kind === 'file') {
                const file = context.files[data.id];
                const coverage = coverageOf((report.files || {})[data.id]);
                return '<strong>' + escapeHtml(baseName(data.id)) + '</strong><span>' + escapeHtml(pathOf(data.id)) + '<br>' + escapeHtml(shortName(file.module)) + ' · ' + plural(file.lines || 0, 'line')
                    + (coverage === null ? '' : ' · ' + coverage + '% covered') + '</span>';
            }
            if (data.kind === 'symbol') {
                const node = context.symbolNodes[data.id];
                return '<strong>' + escapeHtml(node.name) + '</strong><span>' + escapeHtml(pathOf(node.file) + ':' + node.line) + '<br>' + escapeHtml(shortName(node.module)) + ' · '
                    + (node.unused ? 'nothing mentions it' : 'used by ' + plural(node.users, 'function or file', 'functions and files')) + '</span>';
            }
            if (data.kind === 'clone') {
                const clone = context.data.code_map.clones[data.clone];
                return '<strong>Copied code</strong><span>' + clone.files.map(baseName).map(escapeHtml).join(' ⇄ ') + ' · ' + plural(clone.lines, 'line') + '</span>';
            }
            if (data.kind === 'contract') return '<strong>' + escapeHtml(data.label) + '</strong><span>Contract between the repositories</span>';
            return '';
        }

        function scrollToMap() {
            if (!state.expanded) element('#qualityMapSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        function recolor() {
            cy.batch(() => cy.nodes('.module, .dot').forEach((node) => {
                const moduleId = node.data('kind') === 'module' ? node.id() : node.data('module');
                node.data({ color: nodeColor(context.modules[moduleId], context.report, state.colorBy, context.colors, node.data('file')) });
            }));
            chrome();
        }

        // Search: a list of matches under the box, chosen with a click or the arrow keys and Enter. A function opens on
        // Functions, a file on Files.
        function renderMatches() {
            const text = search.value.trim();
            searchResults.innerHTML = matches.map((match, index) => '<li role="option" id="qualitySearchOption' + index + '" class="quality-search__option'
                + (index === activeMatch ? ' is-active' : '') + '" aria-selected="' + (index === activeMatch) + '" data-search-index="' + index + '">'
                + '<i class="fas ' + (match.kind === 'file' ? 'fa-file-code' : 'fa-code') + '" aria-hidden="true"></i>'
                + '<span><strong>' + escapeHtml(match.name) + '</strong><small>' + escapeHtml(match.detail) + '</small></span></li>').join('')
                || (text ? '<li class="quality-search__empty">No function, class or file matches.</li>' : '');
            searchResults.hidden = !text;
            search.setAttribute('aria-expanded', String(!searchResults.hidden));
            if (activeMatch >= 0) search.setAttribute('aria-activedescendant', 'qualitySearchOption' + activeMatch);
            else search.removeAttribute('aria-activedescendant');
        }

        function closeMatches() {
            searchResults.hidden = true;
            search.setAttribute('aria-expanded', 'false');
            search.removeAttribute('aria-activedescendant');
        }

        function chooseMatch(match) {
            if (!match) return;
            closeMatches();
            if (match.kind === 'file') showFile(match.id);
            else showSymbol(match.id);
        }

        search.addEventListener('input', () => {
            matches = context ? matchNames(context.symbolGraph.nodes, context.data.code_map.files, search.value) : [];
            activeMatch = matches.length ? 0 : -1;
            renderMatches();
        });
        search.addEventListener('focus', () => {
            if (search.value.trim() && matches.length) renderMatches();
        });
        search.addEventListener('blur', closeMatches);
        search.addEventListener('keydown', (event) => {
            if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && matches.length) {
                event.preventDefault();
                activeMatch = (activeMatch + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
                renderMatches();
            } else if (event.key === 'Enter') {
                event.preventDefault();
                chooseMatch(matches[activeMatch] || matches[0]);
            } else if (event.key === 'Escape' && search.value) {
                // Esc first empties the box; with the box empty it acts on the map as anywhere else.
                event.preventDefault();
                search.value = '';
                matches = [];
                closeMatches();
            }
        });
        // Pressing a match must not blur the box first, which would close the list before the click lands.
        searchResults.addEventListener('mousedown', (event) => event.preventDefault());
        searchResults.addEventListener('click', (event) => {
            const option = event.target.closest('[data-search-index]');
            if (option) chooseMatch(matches[Number(option.dataset.searchIndex)]);
        });

        root.addEventListener('click', (event) => {
            const target = event.target.closest('[data-select-module], [data-select-link], [data-select-function], [data-select-file], [data-select-clone], [data-show-functions], [data-go-level], [data-explorer-module], [data-explorer-pick], [data-level], [data-color-by], [data-zoom], [data-clear-selection], [data-hide-panel], [data-reset]');
            if (!target || !cy) return;
            event.preventDefault();
            const data = target.dataset;
            const inPanel = Boolean(target.closest('#qualityPanel'));
            if (data.selectModule) go(inPanel ? state.level : 'modules', data.selectModule, frame);
            else if (data.selectLink) showEdge('modules', 'link:' + data.selectLink);
            else if (data.selectFunction) showSymbol(data.selectFunction);
            else if (data.selectFile) showFile(data.selectFile);
            else if (data.selectClone) showEdge('files', 'clone:' + data.selectClone);
            else if (data.showFunctions) showFunctionsOf(data.showFunctions);
            else if (data.goLevel) go(data.goLevel, data.goModule);
            else if (data.explorerPick || (data.explorerModule && (event.ctrlKey || event.metaKey || event.shiftKey))) {
                // The box, or a click with Ctrl, ⌘ or Shift, adds a module to the ones in focus or takes it out.
                const moduleId = data.explorerPick || data.explorerModule;
                go(state.level, state.modules.includes(moduleId) ? state.modules.filter((id) => id !== moduleId) : state.modules.concat(moduleId), frame);
            } else if (data.explorerModule) go(state.level, state.module === data.explorerModule ? null : data.explorerModule, frame);
            else if (data.level) go(data.level, state.modules);
            else if (data.colorBy) {
                state.colorBy = data.colorBy;
                recolor();
            } else if (data.zoom) {
                zoomBy(data.zoom === 'in' ? 1.3 : 1 / 1.3);
            } else if ('hidePanel' in data) {
                setPanelOpen(false);
                if (panelToggle) panelToggle.focus();
            } else if ('clearSelection' in data) {
                clear(true);
            } else if ('reset' in data) {
                search.value = '';
                matches = [];
                closeMatches();
                go(state.level, null, frame);
            }
            if (!inPanel && (data.selectModule || data.selectLink || data.selectFunction || data.selectFile || data.selectClone)) scrollToMap();
        });
        [['#qualityEdgesToggle', 'showEdges'], ['#qualityLabelsToggle', 'showLabels']].forEach(([selector, key]) => {
            element(selector).addEventListener('change', (event) => {
                state[key] = event.target.checked;
                if (cy) applySwitches();
            });
        });
        element('#qualityFit').addEventListener('click', () => {
            if (cy) cy.animate({ fit: { eles: cy.elements(), padding: fitPadding() } }, { duration: 260, easing: 'ease-in-out-cubic' });
        });

        // Expanded view: the workspace (toolbar, map, panel and legend) fills the window below the navbar, which stays
        // usable, and the page behind it stops scrolling. It is a class, not the browser's full screen.
        const workspace = root.querySelector('.quality-workspace');
        const expandButton = element('#qualityFullscreen');
        function placeExpanded() {
            const navbar = document.querySelector('.navbar');
            const top = navbar ? Math.max(0, navbar.getBoundingClientRect().bottom) : 0;
            workspace.style.setProperty('--quality-expanded-top', Math.round(top) + 'px');
        }
        function setExpanded(on) {
            if (!workspace || !expandButton || state.expanded === on) return;
            state.expanded = on;
            // The section keeps its height, so the page under the expanded view does not jump.
            const section = workspace.parentElement;
            section.style.minHeight = on ? section.offsetHeight + 'px' : '';
            if (on) placeExpanded();
            workspace.classList.toggle('is-expanded', on);
            document.documentElement.classList.toggle('quality-scroll-locked', on);
            const label = on ? 'Back to the page' : 'Expand the map to the window';
            expandButton.title = on ? label + ' (Esc)' : label;
            expandButton.setAttribute('aria-label', label);
            expandButton.setAttribute('aria-pressed', String(on));
            const icon = expandButton.querySelector('i');
            if (icon) icon.className = 'fas ' + (on ? 'fa-compress' : 'fa-expand');
            const text = expandButton.querySelector('.quality-tool__text');
            if (text) text.textContent = on ? 'Exit' : 'Expand';
            if (cy) {
                hideTooltip();
                cy.resize();
                cy.fit(cy.elements(), fitPadding());
            }
        }
        if (workspace && expandButton) {
            expandButton.addEventListener('click', () => setExpanded(!state.expanded));
            global.addEventListener('resize', () => {
                if (state.expanded) placeExpanded();
            });
        }

        // The details panel can be hidden to give the map the whole width; selecting something opens it again. Opening,
        // it drops in below the Details button; closed, the button rings briefly, so both directions show which button
        // the panel belongs to.
        const panelToggle = element('#qualityPanelToggle');
        function replay(node, className) {
            node.classList.remove(className);
            void node.offsetWidth;
            node.classList.add(className);
        }
        function setPanelOpen(on) {
            const box = root.querySelector('.quality-workspace');
            if (!box || state.panelOpen === on) return;
            state.panelOpen = on;
            box.classList.toggle('is-panel-hidden', !on);
            if (panelToggle) {
                panelToggle.setAttribute('aria-pressed', String(on));
                panelToggle.title = on ? 'Hide the details panel' : 'Show the details panel';
                if (on) panelToggle.classList.remove('is-nudged');
                else replay(panelToggle, 'is-nudged');
            }
            if (on) replay(element('#qualityPanel'), 'is-opening');
            if (cy) {
                hideTooltip();
                cy.resize();
            }
        }
        if (panelToggle) {
            panelToggle.addEventListener('click', () => setPanelOpen(!state.panelOpen));
            panelToggle.addEventListener('animationend', () => panelToggle.classList.remove('is-nudged'));
            element('#qualityPanel').addEventListener('animationend', (event) => event.target.classList.remove('is-opening'));
        }

        // The page scrolls with the wheel: a plain wheel event is stopped before it reaches the map, which then zooms
        // only with Ctrl or ⌘ held (also what a trackpad pinch sends). Touch pinch-zoom is untouched. In the expanded
        // view there is no page to scroll, so the wheel zooms the map.
        mapElement.parentElement.addEventListener('wheel', (event) => {
            if (!cy) return;
            if (event.ctrlKey || event.metaKey || state.expanded) {
                event.preventDefault();
                return;
            }
            event.stopPropagation();
            flashHint();
        }, { capture: true, passive: false });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape' || !cy || event.defaultPrevented || !root.isConnected) return;
            const typing = event.target.closest && event.target.closest('select, textarea, input:not([type="checkbox"])');
            if (typing && typing !== search) return;
            if (state.expanded) setExpanded(false);
            else clear(true);
        });

        const unavailable = (data) => {
            element('#qualityUnavailableText').innerHTML = unavailableHtml(data);
            element('#qualityUnavailable').hidden = false;
        };
        return global.SharedUtils.fetchJson(root.dataset.apiUrl)
            .then((data) => {
                if (!data.available) {
                    unavailable(data);
                    return;
                }
                element('#qualityContent').hidden = false;
                context = createContext(data, state);
                // Without a report there is still a map: a local `quality.py map` measures nothing.
                const local = data.source === 'local';
                const commit = data.revision ? ' for commit <code>' + escapeHtml(String(data.revision).slice(0, 7)) + '</code>' : '';
                element('#qualityRunEyebrow').textContent = local ? 'Measured on this computer' : 'Measured by CI';
                element('#qualityRunTitle').innerHTML = local ? 'Local run' : 'CI results' + commit;
                element('#qualityWarning').hidden = !local;
                const status = data.report ? runStatus(data.report) : { tone: 'warn', label: 'Map only' };
                const pill = element('#qualityRunStatus');
                pill.className = 'quality-pill quality-pill--' + status.tone;
                pill.textContent = status.label;
                element('#qualitySummary').innerHTML = data.report ? summaryHtml(data) : '';
                root.querySelectorAll('[data-needs-report]').forEach((section) => { section.hidden = !data.report; });
                element('#qualityChecks').innerHTML = checksHtml(context.report);
                element('#qualityTable').innerHTML = tableHtml(context);
                element('#qualityFigures').innerHTML = figuresHtml(context);
                element('#qualityFindings').innerHTML = findingsHtml(context);
                element('#qualityCleanup').innerHTML = cleanupHtml(context);
                element('#qualityBlindSpots').innerHTML = blindSpotsHtml(context);
                cy = global.cytoscape({
                    container: mapElement, style: GRAPH_STYLE, minZoom: 0.15, maxZoom: 10,
                    wheelSensitivity: 0.4, boxSelectionEnabled: false, autoungrabify: true
                });
                // A click focuses: it fades the rest until Esc or a click on the background. A circle around dots is
                // background to a click; double-clicking it goes into it.
                cy.on('tap', (event) => {
                    if (event.target === cy || event.target.data('kind') === 'region') clear(false);
                    else select(event.target);
                });
                cy.on('dbltap', 'node.module', (event) => go('files', event.target.id()));
                cy.on('dbltap', 'node.region', (event) => {
                    if (event.target.data('of') === 'file') showFunctionsOf(event.target.data('region'));
                    else go('symbols', event.target.data('region'));
                });
                cy.on('dbltap', 'node.dot', (event) => {
                    if (event.target.data('kind') === 'file') showFunctionsOf(event.target.id());
                });
                const hoverable = 'node.module, node.contract, node.dot, node.region, edge';
                cy.on('mouseover', hoverable, (event) => {
                    mapElement.style.cursor = 'pointer';
                    hoverStart(event.target);
                });
                cy.on('mouseout', hoverable, () => {
                    mapElement.style.cursor = '';
                    hoverEnd();
                });
                cy.on('viewport', hideTooltip);
                cy.on('zoom', scheduleNames);
                render();
            })
            .catch(() => unavailable(null));
    }

    global.QualityDashboard = {
        aggregateModuleLinks,
        boundaryFindings,
        blindSpots,
        cleanup,
        moduleLevels,
        moduleColumns,
        moduleHierarchy,
        stackedCentres,
        layeredCentres,
        fileGraph,
        fileDots,
        fileSize,
        symbolGraph,
        moduleSymbolGraph,
        symbolSize,
        dotLayout,
        mapView,
        mapElements,
        moduleRing,
        moduleColors,
        packRegions,
        matchNames,
        labelPlaces,
        laneSummary,
        nodeColor,
        createContext,
        escapeHtml,
        init
    };

    document.addEventListener('DOMContentLoaded', () => {
        const root = document.getElementById('qualityDashboard');
        if (root) init(root);
    });
})(window);
