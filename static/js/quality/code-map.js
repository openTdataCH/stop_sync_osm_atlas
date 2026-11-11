/**
 * Code quality dashboard, the code map: what the map of both repositories shows and where everything goes.
 *
 * Reads the code map of the quality evidence: the dependencies between modules, the findings, the graphs of files and
 * of functions, and the layout of each level. A module is a circle, at the same place on Modules and Files; it sits
 * above the modules it declares as dependencies. Nothing here touches the page.
 */
(function (global) {
    'use strict';

    const FONT = '"Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif';
    // The --color-quality-module-1 to -10 tokens: a categorical palette for white, in the order that keeps neighbouring
    // modules apart, including the last slot beside the first.
    const MODULE_PALETTE = ['#2a78d6', '#eb6834', '#17a173', '#99631f', '#d6558a', '#c98500', '#6250d6', '#008300', '#0e93a8', '#e34948'];
    // Modules and Files: the space between the module circles of a column, and between the columns of the two
    // repositories. An arc between two modules bends away from its column by ARC of its length.
    const LAYER_GAP = 46;
    const COLUMN_GAP = 300;
    // The piles of module circles on the Functions level: how far above a dependency a module sits as a share of their
    // radii, the room between piles, and how many places are tried for a circle on each side of where it wants to be.
    const STACK_LIFT = 0.6;
    const STACK_GAP = 60;
    const STACK_STEPS = 400;
    // A code file longer than this is listed as large and ringed on the Files level.
    const FILE_BUDGET = 1000;
    const CODE_FILE = /\.(py|js|mjs|cjs|css|html)$/;
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
    // How close to the edges of the stage the map can be dragged, in pixels.
    const PAN_MARGIN = 80;
    // A dot's name shows once it is at least this tall on screen: at first only on the largest dots.
    // Around a selection every name may show, at least NAMED_FONT map units tall.
    const LABEL_PX = 10;
    // The largest a name grows on screen: zoomed in, names keep this size and take less of the map, so more fit.
    const LABEL_MAX_PX = 13;
    const NAMED_FONT = 9;

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
        return Array.from(new Set(codeMap.modules.map((module) => module.repository))).sort();
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

    /** The links between two files, summed over kinds, with whether each crosses a module border and is declared. */
    function fileLinks(codeMap) {
        const owners = fileOwners(codeMap);
        const declared = declaredDependencies(codeMap);
        const pairs = {};
        codeMap.links.filter(drawn).forEach((link) => {
            const source = owners[link.source];
            const target = owners[link.target];
            if (!source || !target) return;
            const key = link.source + '>' + link.target;
            const entry = pairs[key] || (pairs[key] = {
                source: link.source, target: link.target, count: 0, kinds: {},
                crossing: source !== target, declared: source === target || declared.has(source + '>' + target)
            });
            entry.count += link.count;
            addCount(entry.kinds, link.kind, link.count);
        });
        return Object.values(pairs);
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
            links: fileLinks(codeMap)
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

    /** Each module's colour: the palette in the order of the hierarchy, so the list beside the map runs through it. */
    function moduleColors(codeMap) {
        return Object.fromEntries(moduleHierarchy(codeMap).map((id, index) => [id, MODULE_PALETTE[index % MODULE_PALETTE.length]]));
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
    /**
     * The pan nearest to ``pan`` that keeps the map in view: a map smaller than the stage stays whole inside it, and a
     * larger one keeps covering it, each up to ``margin`` pixels from the edges. ``bounds`` is the box around the map.
     */
    function panWithin(pan, zoom, bounds, width, height, margin = PAN_MARGIN) {
        const within = (value, a, b) => Math.max(Math.min(a, b), Math.min(Math.max(a, b), value));
        return {
            x: within(pan.x, margin - bounds.x1 * zoom, width - margin - bounds.x2 * zoom),
            y: within(pan.y, margin - bounds.y1 * zoom, height - margin - bounds.y2 * zoom)
        };
    }

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

    global.QualityMap = {
        FONT, LAYER_GAP, FILE_BUDGET, NAMED_FONT, shortName, repositoryOf, pathOf, baseName, indexBy, fileOwners,
        drawn, symbolFile, symbolLine, addCount, plural, aggregateModuleLinks, boundaryFindings, blindSpots,
        cleanup, moduleLevels, moduleColumns, layeredCentres, moduleHierarchy, stackedCentres, fileLinks, fileSize,
        fileDots, symbolGraph, moduleSymbolGraph, symbolSize, dotFont, moduleColors, packRegions, dotLayout,
        mapView, matchNames, panWithin, labelPlaces, moduleLines, coverageOf
    };
})(window);
