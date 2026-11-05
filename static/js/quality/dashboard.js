/**
 * Code quality dashboard: the published report and code map, drawn as an interactive module graph, with its files
 * and functions, and as a functions map of every function and class.
 *
 * Arrows point from the code that uses to the code it uses. In the module view a module sits above the
 * modules it declares as dependencies, so an arrow pointing upwards goes against the declared layering.
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
    // Branch coverage in steps of 10%: pale navy for little, full navy for all.
    const COVERAGE_RAMP = Array.from({ length: 10 }, (_, step) => tint(NAVY, 0.14 + 0.86 * step / 9));
    const NOT_MEASURED_COLOR = '#e9ecef';
    // The same values as the --color-quality-* tokens.
    const EDGE_COLORS = { declared: MUTED, undeclared: '#e08e0b', unused: '#adb5bd', internal: '#ced4da', crossing: NAVY, contract: PURPLE };
    // The --color-quality-module-1 to -10 tokens: a categorical palette for white, in the order that keeps neighbouring
    // regions of the functions map apart, including the last slot beside the first.
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
        stale: { label: 'Stale', icon: '', tone: 'muted' },
        not_measured: { label: 'Not measured', icon: '', tone: 'muted' },
        not_applicable: { label: 'Not applicable', icon: '', tone: 'muted' }
    };
    const LANES = [
        ['tests', 'Tests'], ['coverage', 'Branch coverage'], ['mutation', 'Mutation'], ['duplication', 'Duplicated blocks'],
        ['dead_code', 'Python dead code'], ['docs', 'Docs'], ['architecture', 'Architecture']
    ];
    const LEVEL_SPACING = 150;
    const COLUMN_SPACING = 230;
    const REPOSITORY_GAP = 190;
    const FILE_COLUMN_SPACING = 200;
    const FILE_GRID_SPACING = 180;
    const FILE_ROW_SPACING = 46;
    const MAX_FILE_ROWS = 12;
    const BOX_GAP = 80;
    const FUNCTION_COLUMN_SPACING = 210;
    const FUNCTION_ROW_SPACING = 34;
    const MAX_FUNCTION_ROWS = 16;
    // Below this zoom file names are too small to read, so a module opens at least this close.
    const READABLE_ZOOM = 0.8;
    const MODULE_ZOOM = 0.5;
    // A tooltip waits for the cursor to rest, so sweeping across the map shows nothing.
    const HOVER_DELAY = 250;
    const TOOLTIP_GRACE = 120;
    // Functions map: steps of the force layout, space between dots, how much larger than its dots a module's region
    // starts, and the space between regions.
    const SYMBOL_TICKS = 120;
    const SYMBOL_GAP = 1.6;
    const SYMBOL_SPREAD = 1.15;
    const REGION_GAP = 10;
    const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
    const SEARCH_LIMIT = 8;
    // A function found by search opens at least this close, where its neighbours' names can be read.
    const FOCUS_ZOOM = 1.6;
    // A name on the functions map shows once it is at least this tall on screen: at first only on the largest dots.
    // Around a selection every name may show, at least NAMED_FONT map units tall.
    const LABEL_PX = 10;
    // The largest a name grows on screen: zoomed in, names keep this size and take less of the map, so more fit.
    const LABEL_MAX_PX = 13;
    const NAMED_FONT = 9;

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

    /**
     * Layered positions: each repository is a block with dependencies below their dependents and contracts in the gap
     * between blocks. Every module of a repository gets its own column, so a vertical arrow never runs through another module.
     */
    function modulePositions(codeMap) {
        const levels = moduleLevels(codeMap);
        const top = Math.max(0, ...Object.values(levels));
        const positions = {};
        const bounds = {};
        let offset = 0;
        repositoriesOf(codeMap).forEach((repository) => {
            const ids = codeMap.modules.filter((module) => module.repository === repository).map((module) => module.id);
            const lastInRow = {};
            let x = offset - COLUMN_SPACING / 2;
            moduleOrder(codeMap, ids, levels).forEach((id) => {
                const level = levels[id];
                x = Math.max(x + COLUMN_SPACING / 2, lastInRow[level] === undefined ? -Infinity : lastInRow[level] + COLUMN_SPACING);
                lastInRow[level] = x;
                positions[id] = { x, y: (top - level) * LEVEL_SPACING };
            });
            bounds[repository] = { left: offset, right: x };
            offset = x + REPOSITORY_GAP + COLUMN_SPACING / 2;
        });
        const taken = new Set();
        (codeMap.contracts || []).forEach((contract) => {
            const producers = contract.producers.filter((id) => positions[id]);
            const consumers = contract.consumers.filter((id) => positions[id]);
            const ends = producers.concat(consumers);
            if (!ends.length) return;
            const producerRepository = producers.length ? codeMap.modules.find((module) => module.id === producers[0]).repository : null;
            const consumerRepository = consumers.length ? codeMap.modules.find((module) => module.id === consumers[0]).repository : null;
            let x = ends.reduce((sum, id) => sum + positions[id].x, 0) / ends.length;
            if (producerRepository && consumerRepository && producerRepository !== consumerRepository) {
                const [left, right] = [bounds[producerRepository], bounds[consumerRepository]].sort((a, b) => a.left - b.left);
                x = (left.right + right.left) / 2;
            }
            let y = Math.round(ends.reduce((sum, id) => sum + positions[id].y, 0) / ends.length);
            while (taken.has(y)) y += LEVEL_SPACING / 2;
            taken.add(y);
            positions['contract:' + contract.id] = { x, y };
        });
        return positions;
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

    /**
     * One module's files in the middle, in columns by how far each is from where calls enter it; modules that use it
     * on the left and modules it uses on the right, so the arrows crossing its border are its interface.
     */
    function focusPositions(codeMap, graph, focusId) {
        const owners = fileOwners(codeMap);
        const inside = graph.files.filter((file) => file.module === focusId).map((file) => file.id);
        const internal = {};
        const usedInside = new Set();
        inside.forEach((id) => { internal[id] = []; });
        graph.links.forEach((link) => {
            if (!link.crossing && internal[link.source] && internal[link.target]) {
                internal[link.source].push(link.target);
                usedInside.add(link.target);
            }
        });
        const depth = {};
        const queue = inside.filter((id) => graph.entries.has(id) || !usedInside.has(id));
        queue.forEach((id) => { depth[id] = 0; });
        for (let index = 0; index < queue.length; index++) {
            internal[queue[index]].forEach((next) => {
                if (depth[next] === undefined) {
                    depth[next] = depth[queue[index]] + 1;
                    queue.push(next);
                }
            });
        }
        const columns = [];
        inside.forEach((id) => {
            const column = depth[id] === undefined ? 0 : depth[id];
            (columns[column] = columns[column] || []).push(id);
        });
        const positions = {};
        let x = 0;
        let rows = 1;
        columns.filter(Boolean).forEach((column) => {
            for (let start = 0; start < column.length; start += MAX_FILE_ROWS) {
                column.slice(start, start + MAX_FILE_ROWS).forEach((id, row) => { positions[id] = { x, y: row * FILE_ROW_SPACING }; });
                rows = Math.max(rows, Math.min(column.length - start, MAX_FILE_ROWS));
                x += FILE_COLUMN_SPACING;
            }
        });
        const middle = (rows - 1) * FILE_ROW_SPACING / 2;
        const users = new Set();
        const used = new Set();
        graph.links.forEach((link) => {
            if (!link.crossing) return;
            if (owners[link.target] === focusId) users.add(owners[link.source]);
            else if (owners[link.source] === focusId) used.add(owners[link.target]);
        });
        const side = (modules, start, direction) => {
            const boxes = Array.from(modules).sort().map((moduleId) => graph.files.filter((file) => file.module === moduleId).map((file) => file.id));
            const height = boxes.reduce((sum, ids) => sum + Math.min(ids.length, MAX_FILE_ROWS) * FILE_ROW_SPACING, 0) + (boxes.length - 1) * BOX_GAP;
            let y = middle - height / 2;
            boxes.forEach((ids) => {
                ids.forEach((id, index) => {
                    positions[id] = { x: start + direction * Math.floor(index / MAX_FILE_ROWS) * FILE_COLUMN_SPACING, y: y + (index % MAX_FILE_ROWS) * FILE_ROW_SPACING };
                });
                y += Math.min(ids.length, MAX_FILE_ROWS) * FILE_ROW_SPACING + BOX_GAP;
            });
        };
        side(users, -2 * FILE_COLUMN_SPACING, -1);
        side(Array.from(used).filter((moduleId) => !users.has(moduleId)), x + FILE_COLUMN_SPACING, 1);
        return positions;
    }

    /**
     * One file's functions and classes, and the functions and files at the other end of their links: those that use
     * them (``users``) and those they use (``used``), each keyed by file. A file-level end, such as a module-level
     * import, is the file itself and has no member.
     */
    function functionGraph(codeMap, fileId) {
        const owners = fileOwners(codeMap);
        const declared = declaredDependencies(codeMap);
        const symbols = indexBy(codeMap.symbols || [], 'id');
        const fileOf = (id) => (symbols[id] ? symbols[id].file : id);
        const inside = (codeMap.symbols || []).filter((symbol) => symbol.file === fileId)
            .sort((a, b) => a.line - b.line || a.name.localeCompare(b.name)).map((symbol) => symbol.id);
        const pairs = {};
        (codeMap.symbol_links || []).filter(drawn).forEach((link) => {
            if (fileOf(link.source) !== fileId && fileOf(link.target) !== fileId) return;
            const key = link.source + '>' + link.target;
            const sourceModule = owners[fileOf(link.source)];
            const targetModule = owners[fileOf(link.target)];
            const entry = pairs[key] || (pairs[key] = {
                source: link.source, target: link.target, count: 0, kinds: {},
                crossing: sourceModule !== targetModule, declared: sourceModule === targetModule || declared.has(sourceModule + '>' + targetModule)
            });
            entry.count += link.count;
            addCount(entry.kinds, link.kind, link.count);
        });
        const links = Object.values(pairs);
        const users = {};
        const used = {};
        const add = (side, id) => {
            const members = side[fileOf(id)] || (side[fileOf(id)] = []);
            if (symbols[id] && !members.includes(id)) members.push(id);
        };
        links.forEach((link) => {
            if (fileOf(link.target) === fileId && fileOf(link.source) !== fileId) add(users, link.source);
        });
        links.forEach((link) => {
            const other = fileOf(link.target);
            if (fileOf(link.source) !== fileId || other === fileId) return;
            add(users[other] ? users : used, link.target);
        });
        [users, used].forEach((side) => Object.values(side).forEach((members) => members.sort((a, b) => symbols[a].line - symbols[b].line)));
        const entries = new Set(links.filter((link) => link.crossing && fileOf(link.target) === fileId).map((link) => link.target));
        return { file: fileId, inside, users, used, links, entries, symbols };
    }

    /** The opened file's functions in line order in the middle; files that use them on the left, files they use on the right. */
    function functionPositions(graph) {
        const positions = {};
        const rows = Math.max(1, Math.min(graph.inside.length, MAX_FUNCTION_ROWS));
        graph.inside.forEach((id, index) => {
            positions[id] = { x: Math.floor(index / MAX_FUNCTION_ROWS) * FUNCTION_COLUMN_SPACING, y: (index % MAX_FUNCTION_ROWS) * FUNCTION_ROW_SPACING };
        });
        if (!graph.inside.length) positions[graph.file] = { x: 0, y: 0 };
        const right = Math.max(0, Math.ceil(graph.inside.length / MAX_FUNCTION_ROWS) - 1) * FUNCTION_COLUMN_SPACING;
        const middle = (rows - 1) * FUNCTION_ROW_SPACING / 2;
        const side = (files, start, direction) => {
            const boxes = Object.keys(files).sort().map((file) => [file, files[file]]);
            const boxRows = (ids) => Math.max(1, Math.min(ids.length, MAX_FUNCTION_ROWS));
            const height = boxes.reduce((sum, [, ids]) => sum + boxRows(ids) * FUNCTION_ROW_SPACING, 0) + Math.max(0, boxes.length - 1) * BOX_GAP;
            let y = middle - height / 2;
            boxes.forEach(([file, ids]) => {
                if (!ids.length) positions[file] = { x: start, y };
                ids.forEach((id, index) => {
                    positions[id] = { x: start + direction * Math.floor(index / MAX_FUNCTION_ROWS) * FUNCTION_COLUMN_SPACING, y: y + (index % MAX_FUNCTION_ROWS) * FUNCTION_ROW_SPACING };
                });
                y += boxRows(ids) * FUNCTION_ROW_SPACING + BOX_GAP;
            });
        };
        side(graph.users, -2 * FUNCTION_COLUMN_SPACING, -1);
        side(graph.used, right + 2 * FUNCTION_COLUMN_SPACING, 1);
        return positions;
    }

    /** Every module's files as a grid, with the modules in the layers of the module view. */
    function allFilePositions(codeMap, graph) {
        const levels = moduleLevels(codeMap);
        const byModule = {};
        graph.files.forEach((file) => (byModule[file.module] = byModule[file.module] || []).push(file.id));
        const grid = {};
        Object.keys(byModule).forEach((moduleId) => {
            const count = byModule[moduleId].length;
            const columns = Math.max(1, Math.ceil(Math.sqrt(count * 2)));
            grid[moduleId] = { columns, rows: Math.ceil(count / columns) };
        });
        const rowHeight = {};
        Object.keys(grid).forEach((moduleId) => {
            rowHeight[levels[moduleId]] = Math.max(rowHeight[levels[moduleId]] || 0, grid[moduleId].rows * FILE_ROW_SPACING);
        });
        const rowTop = {};
        let y = 0;
        Object.keys(rowHeight).map(Number).sort((a, b) => b - a).forEach((level) => {
            rowTop[level] = y;
            y += rowHeight[level] + 2 * BOX_GAP;
        });
        const positions = {};
        let offset = 0;
        repositoriesOf(codeMap).forEach((repository) => {
            const ids = codeMap.modules.filter((module) => module.repository === repository && grid[module.id]).map((module) => module.id);
            const cursor = {};
            moduleOrder(codeMap, ids, levels).forEach((moduleId) => {
                const level = levels[moduleId];
                const left = cursor[level] === undefined ? offset : cursor[level];
                byModule[moduleId].forEach((id, index) => {
                    positions[id] = {
                        x: left + (index % grid[moduleId].columns) * FILE_GRID_SPACING,
                        y: rowTop[level] + Math.floor(index / grid[moduleId].columns) * FILE_ROW_SPACING
                    };
                });
                cursor[level] = left + grid[moduleId].columns * FILE_GRID_SPACING + BOX_GAP;
            });
            offset = Math.max(offset, ...Object.values(cursor)) + BOX_GAP;
        });
        return positions;
    }

    /**
     * Every function and class as one node. ``users`` counts the distinct functions and files that use it, ``uses`` the
     * functions it uses; links join two functions, summed over kinds. A link to a page draws nothing, as in the other views.
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
                id: symbol.id, name: symbol.name, file: symbol.file, line: symbol.line, module: owners[symbol.file],
                users: size(users, symbol.id), uses: size(uses, symbol.id)
            })),
            links: Object.values(pairs)
        };
    }

    /** Dot diameter. The area grows with the number of users, so a dot used ten times is not ten times as wide. */
    function symbolSize(users) {
        return Math.round((6 + 4.5 * Math.sqrt(users)) * 10) / 10;
    }

    /** Font size of a dot's name, in map units: a larger dot has a larger name, which shows from further away. */
    function symbolFont(users) {
        return Math.round((4 + symbolSize(users) * 0.45) * 10) / 10;
    }

    /** The modules around the functions map, repository by repository, with connected modules side by side. */
    function moduleRing(codeMap) {
        const levels = moduleLevels(codeMap);
        return repositoriesOf(codeMap).flatMap((repository) => moduleOrder(codeMap,
            codeMap.modules.filter((module) => module.repository === repository).map((module) => module.id), levels));
    }

    /**
     * Each module's colour on the functions map: the palette in ring order, starting from the module with the most
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
        for (let step = 0; step < 240; step++) {
            centres.forEach((centre) => {
                centre.x *= 0.98;
                centre.y *= 0.96;
            });
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
     * Positions of the functions map from a small force layout, run to the end before anything is drawn.
     *
     * Each module is a disc: its files, largest first, on a sunflower spiral, and each file's functions on a smaller
     * spiral around the file, so a file starts in one piece. The discs are packed into one round cloud and each is held
     * at its place as a whole; links pull functions that use each other closer, more strongly inside a module, and
     * collisions keep the dots apart. Collisions are found on a grid of cells as wide as the largest pair of dots,
     * so a step costs about as much as there are dots. There is no randomness: the same code map gives the same map.
     */
    function symbolPositions(codeMap, graph, ticks = SYMBOL_TICKS) {
        // A region moves as a whole towards its anchor, so the pull does not crush it; each dot is held only lightly.
        const ANCHOR = 0.08;
        const HOLD = 0.008;
        const SETTLE = 0.6;
        const LINK_INSIDE = 0.3;
        const LINK_ACROSS = 0.01;
        const LINK_GAP = 8;
        const COLLIDE = 0.7;
        const FRICTION = 0.45;
        const ALPHA_END = 0.02;
        const count = graph.nodes.length;
        const positions = {};
        if (!count) return positions;
        const radius = new Float64Array(count);
        const x = new Float64Array(count);
        const y = new Float64Array(count);
        const vx = new Float64Array(count);
        const vy = new Float64Array(count);
        const region = new Int32Array(count);
        const index = {};
        const byModule = {};
        graph.nodes.forEach((node, i) => {
            index[node.id] = i;
            radius[i] = symbolSize(node.users) / 2;
            const files = byModule[node.module] || (byModule[node.module] = {});
            (files[node.file] = files[node.file] || []).push(i);
        });
        const footprint = (i) => Math.PI * (radius[i] + SYMBOL_GAP) * (radius[i] + SYMBOL_GAP) * SYMBOL_SPREAD;
        const listed = moduleRing(codeMap);
        const ring = listed.concat(Object.keys(byModule).filter((id) => !listed.includes(id)).sort()).filter((id) => byModule[id]);
        const discs = {};
        ring.forEach((moduleId) => {
            const files = byModule[moduleId];
            let area = 0;
            Object.keys(files).sort((a, b) => files[b].length - files[a].length || a.localeCompare(b)).forEach((file, fileIndex) => {
                const members = files[file].sort((a, b) => graph.nodes[b].users - graph.nodes[a].users || graph.nodes[a].line - graph.nodes[b].line);
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
            discs[moduleId] = Math.sqrt(area / Math.PI);
        });
        const centres = packRegions(ring.map((moduleId) => discs[moduleId]));
        const anchorX = Float64Array.from(centres, (centre) => centre.x);
        const anchorY = Float64Array.from(centres, (centre) => centre.y);
        ring.forEach((moduleId, m) => Object.values(byModule[moduleId]).forEach((members) => members.forEach((i) => {
            x[i] += anchorX[m];
            y[i] += anchorY[m];
            region[i] = m;
        })));

        const links = graph.links.filter((link) => index[link.source] !== undefined && index[link.target] !== undefined);
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
            strength[k] = (link.crossing ? LINK_ACROSS : LINK_INSIDE) / Math.min(degree[source], degree[target]);
            bias[k] = degree[source] / (degree[source] + degree[target]);
            rest[k] = radius[source] + radius[target] + LINK_GAP;
        });

        let reach = 0;
        for (let i = 0; i < count; i++) reach = Math.max(reach, radius[i] + SYMBOL_GAP);
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
                            const least = radius[i] + radius[j] + 2 * SYMBOL_GAP;
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
            for (let i = 0; i < count; i++) {
                vx[i] *= 1 - FRICTION;
                vy[i] *= 1 - FRICTION;
                x[i] += vx[i];
                y[i] += vy[i];
            }
        }
        graph.nodes.forEach((node, i) => { positions[node.id] = { x: Math.round(x[i] * 10) / 10, y: Math.round(y[i] * 10) / 10 }; });
        return positions;
    }

    /**
     * Functions, classes and files whose name matches ``query``, best first: the exact name, a name starting with it, a
     * name containing it, then a path containing it. Ties go to the most used function and the file with most functions.
     */
    function matchSymbols(graph, query, limit = SEARCH_LIMIT) {
        const text = String(query || '').trim().toLowerCase();
        if (!text) return [];
        const rank = (name, path) => (name === text ? 0 : name.startsWith(text) ? 1 : name.includes(text) ? 2 : path.includes(text) ? 3 : -1);
        const matches = [];
        const files = {};
        graph.nodes.forEach((node) => {
            const score = rank(node.name.toLowerCase(), (pathOf(node.file) + ':' + node.name).toLowerCase());
            if (score >= 0) matches.push({ kind: 'symbol', id: node.id, name: node.name, detail: pathOf(node.file) + ':' + node.line, score, weight: node.users });
            addCount(files, node.file, 1);
        });
        Object.keys(files).forEach((file) => {
            const score = rank(baseName(file).toLowerCase(), pathOf(file).toLowerCase());
            if (score >= 0) {
                matches.push({ kind: 'file', id: file, name: baseName(file), score, weight: files[file],
                    detail: pathOf(file) + ' · ' + plural(files[file], 'function or class', 'functions and classes') });
            }
        });
        return matches.sort((a, b) => a.score - b.score || b.weight - a.weight || a.name.localeCompare(b.name) || a.id.localeCompare(b.id))
            .slice(0, limit).map(({ kind, id, name, detail }) => ({ kind, id, name, detail }));
    }

    /**
     * The names to show on the functions map at ``zoom``: largest dots first, each name at least LABEL_PX tall on
     * screen and kept only if its box, below the dot or else above it, does not overlap a name already kept. With
     * ``only``, the names of those dots whatever their size, ``first`` before the others, as for a selection and its
     * neighbours. ``measure(label, size)`` gives a label's width at a font size. A kept name has ``above`` set when it
     * goes above its dot.
     */
    function labelPlaces(map, zoom, options = {}) {
        const measure = options.measure || ((label, size) => labelWidth(label, size, 600));
        const only = options.only || null;
        const cap = Math.round((LABEL_MAX_PX / zoom) * 10) / 10;
        const fontOf = (node) => Math.min(cap, only ? Math.max(symbolFont(node.users), NAMED_FONT) : symbolFont(node.users));
        const least = LABEL_PX / zoom;
        const margin = 2 / zoom;
        const cell = 80 / zoom;
        const placed = new Map();
        const kept = [];
        const candidates = map.graph.nodes.filter((node) => (only ? only.has(node.id) : symbolFont(node.users) >= least))
            .sort((a, b) => (b.id === options.first) - (a.id === options.first) || b.users - a.users || a.id.localeCompare(b.id));
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
            const half = symbolSize(node.users) / 2;
            return { x1: position.x - half, x2: position.x + half, y1: position.y - half, y2: position.y + half };
        };
        // A named dot is drawn above the smaller ones, so its own disc is an obstacle for their names.
        const place = (node, always) => {
            const font = fontOf(node);
            const position = map.positions[node.id];
            const width = measure(node.name, font) + 2 * margin;
            const half = symbolSize(node.users) / 2;
            const height = font * 1.25 + margin;
            const boxes = [false, true].map((above) => ({
                id: node.id, above, x1: position.x - width / 2, x2: position.x + width / 2,
                y1: above ? position.y - half - height : position.y + half, y2: above ? position.y - half : position.y + half + height
            }));
            const free = (box) => !cellsOf(box).some((key) => (placed.get(key) || [])
                .some((other) => box.x1 < other.x2 && other.x1 < box.x2 && box.y1 < other.y2 && other.y1 < box.y2));
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

    function coverageColor(measurement) {
        if (!measurement || typeof measurement.branches !== 'number') return NOT_MEASURED_COLOR;
        return COVERAGE_RAMP[Math.min(COVERAGE_RAMP.length - 1, Math.floor(measurement.branches / 10))];
    }

    /** ``colors`` gives each module its own colour when ``colorBy`` is ``module``, as on the functions map. */
    function nodeColor(module, report, colorBy, colors) {
        if (colorBy === 'module') return (colors || {})[module.id] || NOT_MEASURED_COLOR;
        if (colorBy === 'repository') return (REPOSITORIES[module.repository] || {}).color || NOT_MEASURED_COLOR;
        if (colorBy === 'coverage') return coverageColor(((report.modules || {})[module.id] || {}).coverage);
        return (CRITICALITY[module.criticality] || {}).color || NOT_MEASURED_COLOR;
    }

    /** Fill, label and border colours of a box filled with ``color``: white text on dark fills, ink on light ones. */
    function paint(color) {
        const luminance = [1, 3, 5].reduce((sum, offset, index) => sum + [0.2126, 0.7152, 0.0722][index] * parseInt(color.slice(offset, offset + 2), 16) / 255, 0);
        return {
            color,
            textColor: luminance < 0.55 ? '#ffffff' : INK,
            borderColor: color === NOT_MEASURED_COLOR ? '#adb5bd' : color
        };
    }

    function edgeWidth(count) {
        return Math.min(8, 1.5 + 1.3 * Math.log2(1 + count));
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
        } else if (lane === 'mutation' && typeof item.score === 'number') {
            text = item.score + '%';
            detail = item.killed + ' of ' + item.total + ' mutants killed';
        } else if ((lane === 'duplication' || lane === 'dead_code') && typeof item.count === 'number') {
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

    /** A value with its status. Only pass, fail and attention get an icon; stale and missing values are muted text. */
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

    function moduleElements(codeMap, report, options) {
        const positions = modulePositions(codeMap);
        const lines = moduleLines(codeMap);
        const largest = Math.max(1, ...Object.values(lines));
        const elements = repositoriesOf(codeMap).map((repository) => ({
            group: 'nodes', classes: 'repository',
            data: { id: 'repository:' + repository, label: (REPOSITORIES[repository] || {}).label || repository, kind: 'repository' }
        }));
        codeMap.modules.forEach((module) => elements.push({
            group: 'nodes', classes: 'module', position: positions[module.id],
            data: Object.assign({
                id: module.id, parent: 'repository:' + module.repository, label: shortName(module.id), kind: 'module',
                height: Math.round(36 + 26 * Math.sqrt((lines[module.id] || 0) / largest))
            }, paint(nodeColor(module, report, options.colorBy)))
        }));
        (codeMap.contracts || []).forEach((contract) => {
            const id = 'contract:' + contract.id;
            if (!positions[id]) return;
            elements.push({ group: 'nodes', classes: 'contract', position: positions[id], data: { id, label: contract.title, kind: 'contract' } });
            contract.producers.concat(contract.consumers).filter((moduleId) => positions[moduleId]).forEach((moduleId) => elements.push({
                group: 'edges', classes: 'contract-link', data: { id: id + '~' + moduleId, source: moduleId, target: id, kind: 'contract-link' }
            }));
        });
        options.moduleLinks.filter((link) => link.count > 0 || options.showUnused).forEach((link) => elements.push({
            group: 'edges',
            classes: link.count === 0 ? 'unused' : link.declared ? 'declared' : 'undeclared',
            data: {
                id: 'link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'module-link',
                width: link.count ? edgeWidth(link.count) : 1.5, label: link.count ? String(link.count) : ''
            }
        }));
        return elements;
    }

    function fileElements(codeMap, report, options) {
        const graph = fileGraph(codeMap, options.focus);
        const modules = indexBy(codeMap.modules, 'id');
        const positions = options.focus ? focusPositions(codeMap, graph, options.focus) : allFilePositions(codeMap, graph);
        const elements = Array.from(new Set(graph.files.map((file) => file.module))).map((moduleId) => ({
            group: 'nodes', classes: 'file-module' + (!options.focus ? ' overview' : moduleId !== options.focus ? ' outside' : ''),
            data: { id: moduleId, label: shortName(moduleId), kind: 'module' }
        }));
        graph.files.forEach((file) => elements.push({
            group: 'nodes', classes: 'file' + (graph.entries.has(file.id) ? ' entry' : ''), position: positions[file.id],
            data: Object.assign({ id: file.id, parent: file.module, label: baseName(file.id), kind: 'file' }, paint(nodeColor(modules[file.module], report, options.colorBy)))
        }));
        graph.links.forEach((link) => elements.push({
            group: 'edges', classes: !link.crossing ? 'internal' : link.declared ? 'crossing' : 'crossing undeclared',
            data: { id: 'file-link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'file-link', kinds: kindsText(link.kinds), width: edgeWidth(link.count) / 1.5 }
        }));
        return elements;
    }

    function functionElements(codeMap, report, options) {
        const graph = functionGraph(codeMap, options.file);
        const positions = functionPositions(graph);
        const modules = indexBy(codeMap.modules, 'id');
        const owners = fileOwners(codeMap);
        const elements = [];
        const box = (file, outside) => elements.push({
            group: 'nodes', classes: 'function-file' + (outside ? ' outside' : ' focus'), position: positions[file],
            data: { id: file, label: baseName(file) + (owners[file] !== owners[graph.file] ? ' · ' + shortName(owners[file]) : ''), kind: 'function-file', module: owners[file] }
        });
        const member = (id, file) => elements.push({
            group: 'nodes', classes: 'function' + (graph.entries.has(id) ? ' entry' : ''), position: positions[id],
            data: Object.assign({ id, parent: file, label: graph.symbols[id].name, kind: 'function', module: owners[file] },
                paint(nodeColor(modules[owners[file]], report, options.colorBy)))
        });
        box(graph.file, false);
        graph.inside.forEach((id) => member(id, graph.file));
        [graph.users, graph.used].forEach((side) => Object.keys(side).forEach((file) => {
            box(file, true);
            side[file].forEach((id) => member(id, file));
        }));
        graph.links.forEach((link) => elements.push({
            group: 'edges', classes: !link.crossing ? 'internal' : link.declared ? 'crossing' : 'crossing undeclared',
            data: { id: 'function-link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'function-link', kinds: kindsText(link.kinds), width: edgeWidth(link.count) / 1.5 }
        }));
        return elements;
    }

    /** Every function and class as a dot, sized by its users; the name sits below, larger on a larger dot. */
    function symbolElements(codeMap, report, options) {
        const map = options.symbolMap;
        const modules = indexBy(codeMap.modules, 'id');
        const elements = map.graph.nodes.map((node) => {
            const size = symbolSize(node.users);
            return {
                group: 'nodes', classes: 'symbol', position: map.positions[node.id],
                data: {
                    id: node.id, label: node.name, kind: 'symbol', module: node.module, size, users: node.users,
                    font: symbolFont(node.users), color: nodeColor(modules[node.module], report, options.symbolColorBy, map.colors)
                }
            };
        });
        map.graph.links.forEach((link) => elements.push({
            group: 'edges', classes: 'symbol-link ' + (!link.crossing ? 'internal' : link.declared ? 'crossing' : 'crossing undeclared'),
            data: { id: 'symbol-link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'symbol-link', kinds: kindsText(link.kinds) }
        }));
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
        { selector: 'node.module, node.file', style: {
            shape: 'round-rectangle', 'background-color': 'data(color)', 'border-width': 1, 'border-color': 'data(borderColor)',
            label: 'data(label)', color: 'data(textColor)', 'text-valign': 'center', 'text-halign': 'center',
            'underlay-color': NAVY, 'underlay-opacity': 0, 'underlay-padding': 5, 'underlay-shape': 'round-rectangle'
        } },
        { selector: 'node.module', style: {
            width: (node) => labelWidth(node.data('label'), 14, 600) + 28, height: 'data(height)', 'corner-radius': 10,
            'font-size': 14, 'font-weight': 600
        } },
        { selector: 'node.file', style: {
            width: (node) => labelWidth(node.data('label'), 11, 500) + 16, height: 24, 'corner-radius': 6,
            'font-size': 11, 'font-weight': 500, 'min-zoomed-font-size': 7
        } },
        { selector: 'node.function', style: {
            shape: 'round-rectangle', 'background-color': 'data(color)', 'border-width': 1, 'border-color': 'data(borderColor)',
            label: 'data(label)', color: 'data(textColor)', 'text-valign': 'center', 'text-halign': 'center',
            width: (node) => labelWidth(node.data('label'), 11, 500) + 14, height: 22, 'corner-radius': 5,
            'font-size': 11, 'font-weight': 500, 'min-zoomed-font-size': 7,
            'underlay-color': NAVY, 'underlay-opacity': 0, 'underlay-padding': 5, 'underlay-shape': 'round-rectangle'
        } },
        { selector: 'node.file.entry, node.function.entry', style: { 'outline-width': 1.5, 'outline-color': INK, 'outline-opacity': 0.6, 'outline-offset': 2 } },
        { selector: 'node.repository, node.file-module', style: {
            label: 'data(label)', 'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -8, 'text-transform': 'uppercase',
            'font-size': 12, 'font-weight': 700, color: MUTED, 'background-color': '#f8f9fa', 'background-opacity': 1,
            'border-width': 1, 'border-color': '#e5e7eb', shape: 'round-rectangle', 'corner-radius': 14, padding: 30
        } },
        // File boxes are drawn small when a whole repository fits the screen; a larger name keeps them legible.
        { selector: 'node.file-module', style: { 'font-size': 14, padding: 18 } },
        { selector: 'node.file-module.overview', style: { 'font-size': 30, color: INK, 'text-margin-y': -12 } },
        { selector: 'node.file-module.outside', style: { 'background-color': '#ffffff', 'border-style': 'dashed', 'border-color': '#ced4da' } },
        { selector: 'node.function-file', style: {
            label: 'data(label)', 'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -6,
            'font-size': 12, 'font-weight': 600, color: MUTED, 'background-color': '#f8f9fa', 'background-opacity': 1,
            'border-width': 1, 'border-color': '#e5e7eb', shape: 'round-rectangle', 'corner-radius': 10, padding: 14
        } },
        { selector: 'node.function-file.outside', style: { 'background-color': '#ffffff', 'border-style': 'dashed', 'border-color': '#ced4da' } },
        // A file reached only at module level has no functions to hold: it is a plain box with its name inside.
        { selector: 'node.function-file:childless', style: {
            width: (node) => labelWidth(node.data('label'), 11, 500) + 16, height: 24, 'text-valign': 'center', 'text-margin-y': 0,
            'font-size': 11, 'font-weight': 500, color: INK
        } },
        { selector: 'node.contract', style: {
            shape: 'diamond', width: 22, height: 22, 'background-color': PURPLE, label: 'data(label)',
            'text-valign': 'bottom', 'text-margin-y': 6, 'text-wrap': 'wrap', 'text-max-width': 120, 'font-size': 11, 'font-weight': 600, color: PURPLE,
            'text-background-color': '#ffffff', 'text-background-opacity': 0.9, 'text-background-padding': 2, 'text-background-shape': 'round-rectangle'
        } },
        { selector: 'edge', style: {
            width: 'data(width)', 'curve-style': 'bezier', 'control-point-step-size': 36, 'target-arrow-shape': 'triangle', 'arrow-scale': 0.8,
            'line-color': EDGE_COLORS.declared, 'target-arrow-color': EDGE_COLORS.declared, 'line-opacity': 0.55,
            'transition-property': 'opacity, line-opacity', 'transition-duration': 150
        } },
        { selector: 'edge.unused', style: { 'line-color': EDGE_COLORS.unused, 'target-arrow-color': EDGE_COLORS.unused, 'line-style': 'dotted', 'line-opacity': 0.9 } },
        { selector: 'edge.internal', style: { 'line-color': EDGE_COLORS.internal, 'target-arrow-color': EDGE_COLORS.internal, 'arrow-scale': 0.6, 'line-opacity': 0.8 } },
        { selector: 'edge.crossing', style: { 'line-color': EDGE_COLORS.crossing, 'target-arrow-color': EDGE_COLORS.crossing, 'line-opacity': 0.5 } },
        // After .crossing: an undeclared crossing edge must look undeclared.
        { selector: 'edge.undeclared', style: {
            'line-color': EDGE_COLORS.undeclared, 'target-arrow-color': EDGE_COLORS.undeclared, 'line-style': 'dashed', 'line-dash-pattern': [7, 4], 'line-opacity': 0.9
        } },
        { selector: 'edge.contract-link', style: {
            width: 1.5, 'line-color': EDGE_COLORS.contract, 'line-style': 'dotted', 'target-arrow-shape': 'none', 'curve-style': 'straight', 'line-opacity': 0.6
        } },
        // Functions map. Only dots marked .labelled show their name, which the script sets from the zoom (LABEL_PX), so
        // at first only the largest dots are named and more names appear when zoomed in, at most LABEL_MAX_PX tall. Lines are thin and faint, and
        // let clicks through to the dots.
        { selector: 'node.symbol', style: {
            shape: 'ellipse', width: 'data(size)', height: 'data(size)', 'background-color': 'data(color)', 'border-width': 0,
            label: '', 'font-size': 'data(font)', 'font-weight': 600, color: INK, 'text-valign': 'bottom', 'text-halign': 'center',
            'text-margin-y': 1, 'text-outline-color': '#ffffff', 'text-outline-width': 1.5, 'text-outline-opacity': 0.9,
            'z-index': 'data(users)', 'underlay-color': NAVY, 'underlay-opacity': 0, 'underlay-padding': 3,
            'underlay-shape': 'ellipse', 'transition-duration': 0
        } },
        // A named dot is drawn above the unnamed ones, so no dot covers a name.
        { selector: 'node.symbol.labelled', style: { label: 'data(label)', 'font-size': (node) => node.data('labelFont') || node.data('font'), 'z-index': (node) => 500 + node.data('users') } },
        { selector: 'node.symbol.above', style: { 'text-valign': 'top', 'text-margin-y': -1 } },
        { selector: 'node.symbol.unlabelled', style: { label: '' } },
        { selector: 'edge.symbol-link', style: {
            'curve-style': 'haystack', 'haystack-radius': 0, width: 0.6, 'line-color': EDGE_COLORS.unused, 'line-style': 'solid',
            'line-opacity': 0.4, 'target-arrow-shape': 'none', events: 'no', 'transition-duration': 0
        } },
        { selector: 'edge.symbol-link.hidden', style: { display: 'none' } },
        // Focus, from a click: the rest of the graph steps back but stays readable.
        { selector: '.faded', style: { opacity: 0.35 } },
        { selector: 'edge.lit', style: { 'line-opacity': 1, 'z-index': 10 } },
        { selector: 'edge.lit[label]', style: {
            label: 'data(label)', 'font-family': FONT, 'font-size': 11, 'font-weight': 600, color: INK, 'text-rotation': 'none',
            'text-background-color': '#ffffff', 'text-background-opacity': 1, 'text-background-padding': 3, 'text-background-shape': 'round-rectangle',
            'text-border-width': 1, 'text-border-color': '#e5e7eb', 'text-border-opacity': 1
        } },
        // Hover only marks: a darker outline on the box and thicker arrows of its own. Nothing else changes.
        { selector: 'node.hover', style: { 'underlay-opacity': 0.14, 'border-width': 2, 'border-color': INK } },
        { selector: 'edge.hover', style: { width: (edge) => (edge.data('width') || 1.5) + 1.5, 'line-opacity': 1, 'z-index': 9 } },
        // A selected function's own lines keep their meaning: grey inside its module, navy or orange across a boundary.
        { selector: 'edge.symbol-link.lit, edge.symbol-link.hover', style: {
            display: 'element', 'curve-style': 'straight', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.5, width: 1.1,
            'line-color': EDGE_COLORS.declared, 'target-arrow-color': EDGE_COLORS.declared, 'line-opacity': 0.85, 'z-index': 10
        } },
        { selector: 'edge.symbol-link.lit.crossing', style: { 'line-color': NAVY, 'target-arrow-color': NAVY } },
        { selector: 'edge.symbol-link.lit.undeclared', style: {
            'line-color': EDGE_COLORS.undeclared, 'target-arrow-color': EDGE_COLORS.undeclared, 'line-style': 'dashed', 'line-dash-pattern': [5, 3]
        } },
        // Faded dots drop their names, so the names of the selection and its neighbours stand out.
        { selector: 'node.symbol.faded', style: { opacity: 0.16, label: '' } },
        { selector: 'edge.symbol-link.faded', style: { opacity: 0.08 } },
        { selector: 'node.symbol.named', style: { label: 'data(label)', 'font-size': (node) => node.data('labelFont') || Math.max(node.data('font'), NAMED_FONT), 'z-index': 1000 } },
        { selector: 'node.symbol.hover', style: { 'border-width': 1.5, 'border-color': INK, 'underlay-opacity': 0.18 } },
        { selector: 'node:selected', style: { 'underlay-opacity': 0.3, 'underlay-padding': 6 } },
        { selector: 'edge:selected', style: { 'underlay-color': NAVY, 'underlay-opacity': 0.2, 'underlay-padding': 5 } }
    ];

    /** The colour encoding the current view uses: the functions map keeps its own, by module unless changed. */
    function colorChoice(state) {
        return state.view === 'symbols' ? state.symbolColorBy : state.colorBy;
    }

    function legendHtml(state) {
        const items = [];
        const swatch = (color, label) => '<li><span class="quality-swatch" style="background:' + color + '" aria-hidden="true"></span>' + label + '</li>';
        const colorBy = colorChoice(state);
        if (colorBy === 'module') {
            items.push('<li>Dot colour: the module, as in the list beside the map</li>');
        } else if (colorBy === 'criticality') {
            Object.keys(CRITICALITY).forEach((level) => items.push('<li>' + criticalityBadge(level) + '</li>'));
        } else if (colorBy === 'coverage') {
            items.push('<li><span class="quality-ramp" style="background:linear-gradient(90deg,' + COVERAGE_RAMP.join(',') + ')" aria-hidden="true"></span>Branch coverage 0% to 100%</li>');
            items.push(swatch(NOT_MEASURED_COLOR, 'No runtime code or not measured'));
        } else {
            Object.keys(REPOSITORIES).forEach((repository) => items.push(swatch(REPOSITORIES[repository].color, REPOSITORIES[repository].label)));
        }
        items.push('<li class="quality-legend__break" aria-hidden="true"></li>');
        const line = (kind, label) => '<li><span class="quality-line quality-line--' + kind + '" aria-hidden="true"></span>' + label + '</li>';
        if (state.view === 'symbols') {
            items.push(line('symbol', 'A call or reference between two functions'));
            items.push(line('declared', 'Selected: inside one module'));
            items.push(line('crossing', 'Selected: across a declared module dependency'));
            items.push(line('undeclared', 'Selected: across an undeclared one'));
            items.push('<li class="quality-legend__break" aria-hidden="true"></li>');
            items.push('<li><span class="quality-dots" aria-hidden="true"><span></span><span></span><span></span></span>Dot size: how many functions and files use it</li>');
            items.push('<li>Names show on the largest dots; zoom in for more, or hover a dot.</li>');
        } else if (state.view === 'modules') {
            items.push(line('declared', 'Code dependency the catalog declares'));
            items.push(line('undeclared', 'Code dependency the catalog does not declare'));
            if (state.showUnused) items.push(line('unused', 'Declared, but no code reference found'));
            items.push('<li><span class="quality-swatch quality-swatch--contract" aria-hidden="true"></span>Contract between repositories</li>');
            items.push('<li>Box height: lines of code. Hover an arrow for its code references.</li>');
        } else {
            items.push(line('internal', 'Inside one module'));
            items.push(line('crossing', 'Across a declared module dependency'));
            items.push(line('undeclared', 'Across an undeclared module dependency'));
            items.push('<li><span class="quality-swatch quality-swatch--entry" aria-hidden="true"></span>Ringed: '
                + (state.view === 'functions' ? 'function' : 'file') + ' used from another module</li>');
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

    const CLOSE_BUTTON = '<button type="button" class="quality-panel__close" data-clear-selection title="Close (Esc)" aria-label="Close details"><i class="fas fa-times" aria-hidden="true"></i></button>';

    function overviewHtml(state) {
        if (state.view === 'symbols') {
            return '<p class="quality-eyebrow">Functions map</p>'
                + '<h2 class="quality-panel__title">How to read the functions map</h2>'
                + '<ol class="quality-steps">'
                + '<li>Each dot is a function or class of either repository, coloured by its module, so each module forms its own region. A file\'s functions start side by side.</li>'
                + '<li>A larger dot is used by more functions and files. Names show on the largest dots; zoom in for more, or hover a dot for its name.</li>'
                + '<li>A line joins a function to one it calls or references. Calls through objects, such as <code>self.save()</code> or <code>this.render()</code>, are not seen.</li>'
                + '<li>Click a module in the list to pick out its functions, and click it again or <strong>Reset</strong> to clear.</li>'
                + '<li>Select a dot for its callers and callees; double-click it to open its file. Search finds a function, class or file by name.</li>'
                + '<li>The module map stays the place to review boundaries: this map is for exploring.</li>'
                + '</ol>';
        }
        if (state.view === 'functions') {
            return '<p class="quality-eyebrow">File functions</p>'
                + '<h2 class="quality-panel__title">How to read the functions</h2>'
                + '<ol class="quality-steps">'
                + '<li>The opened file\'s functions and classes are in the middle, in line order. What uses them is on the left, what they use on the right, grouped by file.</li>'
                + '<li>Arrows are calls, imported or shared names, HTTP requests and templates rendered. A box holding no function is reached at file level, such as a module-level import.</li>'
                + '<li>Calls through objects, such as <code>self.save()</code>, are not seen.</li>'
                + '<li>A ringed function is used from another module.</li>'
                + '<li>Select a function for its callers and callees. Double-click one on either side to open its file.</li>'
                + '<li>Press <kbd>Esc</kbd> or use the module name at the top left to go back to the module\'s files.</li>'
                + '</ol>';
        }
        if (state.view === 'files') {
            return '<p class="quality-eyebrow">' + (state.focus ? 'Module files' : 'All files') + '</p>'
                + '<h2 class="quality-panel__title">How to read the files</h2>'
                + '<ol class="quality-steps">'
                + (state.focus
                    ? '<li>The opened module is in the middle. Modules that use it are on the left, modules it uses on the right.</li>'
                        + '<li>Inside, files are ordered by how far they are from where calls enter the module.</li>'
                    : '<li>Every module\'s files, with the modules in the layers of the module view.</li>')
                + '<li>A ringed file is used from another module: the arrows crossing a border are the module\'s actual interface.</li>'
                + '<li>Select a file to focus on its links and see its details; double-click it to open its functions.</li>'
                + '<li>Press <kbd>Esc</kbd> or use <strong>All modules</strong> at the top left to go back.</li>'
                + '</ol>';
        }
        return '<p class="quality-eyebrow">Module map</p>'
            + '<h2 class="quality-panel__title">How to read the map</h2>'
            + '<ol class="quality-steps">'
            + '<li>Each box is a module: a group of files with one responsibility in the module catalog.</li>'
            + '<li>An arrow goes from the module whose code uses another module to the module it uses: imports, calls, shared browser names, script loads, HTTP requests and templates. A link to a page draws no arrow.</li>'
            + '<li>A module sits above the modules it lists as dependencies in the catalog, so declared dependencies point down.</li>'
            + '<li>An orange dashed arrow is a code dependency the catalog does not declare.</li>'
            + '<li>Select a module to focus on its dependencies and see its details, and double-click it to open its files. <kbd>Esc</kbd> or a click on the background clears the focus.</li>'
            + '<li>Drag to move. Zoom with the buttons or <kbd>Ctrl</kbd>/<kbd>⌘</kbd> and scroll.</li>'
            + '</ol>';
    }

    function moduleHtml(context, moduleId) {
        const module = context.modules[moduleId];
        const row = (context.data.report.modules || {})[moduleId] || {};
        const interfaceRows = (context.data.code_map.interface || {})[moduleId] || [];
        const declared = new Set(module.entrypoints.map((entry) => entry.symbol).filter(Boolean));
        const usedIds = new Set(interfaceRows.map((symbol) => symbol.id));
        const outgoing = context.moduleLinks.filter((link) => link.source === moduleId);
        const incoming = context.moduleLinks.filter((link) => link.target === moduleId);
        const lanes = LANES.map(([lane, label]) => {
            const summary = laneSummary(row, lane);
            return '<div><dt>' + label + '</dt><dd>' + statusBadge(summary.status, summary.text)
                + (summary.detail ? '<small>' + escapeHtml(summary.detail) + '</small>' : '') + '</dd></div>';
        }).join('');
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
        const open = context.state.view === 'files' && context.state.focus === moduleId ? ''
            : '<p><button type="button" class="quality-button" data-open-module="' + escapeHtml(module.id) + '"><i class="fas fa-folder-open" aria-hidden="true"></i> Open module files</button></p>';
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">' + escapeHtml((REPOSITORIES[module.repository] || {}).label || module.repository) + ' module</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(module.title) + '</h2>'
            + '<div class="quality-panel__meta"><code>' + escapeHtml(module.id) + '</code>' + criticalityBadge(module.criticality) + '</div>'
            + '<p>' + escapeHtml(module.responsibility) + '</p>'
            + '<p class="quality-muted">' + escapeHtml((CRITICALITY[module.criticality] || {}).meaning || '') + '</p>'
            + open
            + '<h3 class="quality-panel__subtitle">Evidence</h3><dl class="quality-kv">' + lanes + '</dl>'
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

    function fileHtml(context, fileId) {
        const file = context.files[fileId];
        const owners = context.owners;
        const lines = (links, end) => links.map((link) => sourceLink(context.data, link[end]) + (owners[link[end]] !== file.module ? ' <span class="quality-tag">' + escapeHtml(shortName(owners[link[end]])) + '</span>' : '')
            + '<small>' + escapeHtml(kindsText(link.kinds)) + '</small>');
        const graph = fileGraph(context.data.code_map, file.module);
        const outgoing = graph.links.filter((link) => link.source === fileId);
        const incoming = graph.links.filter((link) => link.target === fileId);
        const used = ((context.data.code_map.interface || {})[file.module] || []).filter((symbol) => symbol.file === fileId);
        const routes = (context.data.code_map.routes || []).filter((route) => route.file === fileId);
        const pageLinks = {};
        context.data.code_map.links.filter((link) => !drawn(link) && link.source === fileId).forEach((link) => addCount(pageLinks, link.target, link.count));
        const open = context.state.view === 'functions' && context.state.file === fileId ? ''
            : '<p><button type="button" class="quality-button" data-open-file="' + escapeHtml(fileId) + '"><i class="fas fa-code" aria-hidden="true"></i> Open file functions</button></p>';
        const reached = (route) => [route.requested_by.length ? 'requested by ' + route.requested_by.map(baseName).map(escapeHtml).join(', ') : '',
            route.linked_by.length ? 'linked from ' + route.linked_by.map(baseName).map(escapeHtml).join(', ') : ''].filter(Boolean).join('; ')
            || 'Nothing in the code reaches it';
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">File in ' + escapeHtml(shortName(file.module)) + '</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(baseName(fileId)) + '</h2>'
            + '<p>' + sourceLink(context.data, fileId) + '</p>'
            + '<p class="quality-muted">' + plural(file.lines || 0, 'line') + ', ' + plural(file.symbols || 0, 'function or class', 'functions and classes') + '.</p>'
            + open
            + '<h3 class="quality-panel__subtitle">Used from other modules (' + used.length + ')</h3>'
            + list(used.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code><small>by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', ') + '</small>'), 'Nothing in this file.')
            + (routes.length ? '<h3 class="quality-panel__subtitle">Routes (' + routes.length + ')</h3>'
                + list(routes.map((route) => ['<code>' + escapeHtml(route.pattern) + '</code>', escapeHtml(route.methods.join(', ')), reached(route)]), '') : '')
            + '<h3 class="quality-panel__subtitle">Uses</h3>' + list(lines(outgoing, 'target'), 'No other file.')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(lines(incoming, 'source'), 'No other file.')
            + (Object.keys(pageLinks).length ? '<h3 class="quality-panel__subtitle">Links to pages</h3>'
                + list(Object.keys(pageLinks).sort().map((target) => [sourceLink(context.data, target), plural(pageLinks[target], 'link')]), '') : '');
    }

    /** A function's callers and callees, each a button that opens it in its file. */
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
                : '<a href="#' + escapeHtml(id) + '" class="quality-link" data-open-file="' + escapeHtml(id) + '">' + escapeHtml(baseName(id)) + '</a> (file level)';
            return name + tag + '<small>' + sourceLink(context.data, file, other ? other.line : null) + '</small>';
        };
        const rows = (side, other) => links.filter((link) => link[side] === symbolId)
            .sort((a, b) => a[other].localeCompare(b[other]) || a.kind.localeCompare(b.kind))
            .map((link) => [end(link[other]), escapeHtml(kindsText({ [link.kind]: link.count }))]);
        // On the functions map the file is one double-click away; this is the same step for the keyboard.
        const open = context.state.view !== 'symbols' ? ''
            : '<p class="quality-muted">In module ' + moduleButton(moduleId) + '.</p>'
                + '<p><button type="button" class="quality-button" data-open-file="' + escapeHtml(symbol.file) + '" data-open-symbol="' + escapeHtml(symbolId) + '">'
                + '<i class="fas fa-code" aria-hidden="true"></i> Open file functions</button></p>';
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">Function in ' + escapeHtml(baseName(symbol.file)) + '</p>'
            + '<h2 class="quality-panel__title"><code>' + escapeHtml(symbol.name) + '</code></h2>'
            + '<p>' + sourceLink(context.data, symbol.file, symbol.line) + '</p>'
            + open
            + (route ? '<p>Answers <code>' + escapeHtml(route.methods.join(', ') + ' ' + route.pattern) + '</code>.</p>' : '')
            + (usedBy ? '<p class="quality-muted">Used from ' + usedBy.used_by.map(shortName).map(escapeHtml).join(', ') + '.</p>' : '')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(rows('target', 'source'), 'Nothing the map can see.')
            + '<h3 class="quality-panel__subtitle">Uses</h3>' + list(rows('source', 'target'), 'Nothing the map can see.');
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

    /** A titled list with its count; ``warn`` marks a non-empty list as something to act on. */
    function findingGroup(title, lead, items, empty, warn = true) {
        return '<div class="quality-finding' + (warn && items.length ? ' quality-finding--warn' : '') + '">'
            + '<div class="quality-finding__head"><h3>' + title + '</h3><span class="quality-finding__count">' + items.length + '</span></div>'
            + '<p>' + lead + '</p>' + list(items, empty) + '</div>';
    }

    function findingsHtml(context) {
        const findings = context.findings;
        const group = findingGroup;
        const privateItems = findings.privateNames.map((symbol) => ['<code>' + escapeHtml(symbol.name) + '</code> in ' + moduleButton(symbol.module),
            'used by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', '), sourceLink(context.data, symbol.file, symbol.line)]);
        return group('Undeclared module dependencies', 'Code in one module references another module the catalog does not list as a dependency.',
            findings.undeclared.map((link) => [linkButton(link), plural(link.count, 'reference')]), 'None.')
            + group('Modules that depend on each other', 'Each of the two modules references the other, so neither can change in isolation.',
                findings.cycles.map((link) => moduleButton(link.source) + ' ⇄ ' + moduleButton(link.target)), 'None.')
            + group('Private names used across a boundary', 'A name starting with <code>_</code> is internal to its module, but another module uses it.', privateItems, 'None.')
            + group('Declared dependencies without code references', 'These may go through the database or a URL built at runtime, which the map does not see, or the declaration is out of date.',
                findings.unused.map(linkButton), 'None.');
    }

    function blindSpotsHtml(context) {
        const data = context.data;
        const spots = blindSpots(data.code_map);
        const at = (row) => sourceLink(data, row.file, row.line);
        return findingGroup('References that reach nothing', 'A URL, <code>url_for</code> endpoint or template name in the code that the app does not serve: a typo, or a route that was removed.',
            spots.unmatched.map((row) => ['<code>' + escapeHtml(row.reference) + '</code>', escapeHtml(UNMATCHED_KINDS[row.kind] || row.kind), at(row)]), 'None.')
            + findingGroup('Routes nothing in the code reaches', 'No script, template or view requests or links to these. They may serve outside clients, crawlers or links in the documentation, or be unused.',
                spots.unreached.map((route) => ['<code>' + escapeHtml(route.pattern) + '</code>', escapeHtml(route.methods.join(', ')), sourceLink(data, route.file, route.line)]), 'None.', false)
            + findingGroup('URLs and templates chosen at runtime', 'The code computes the URL, endpoint or template when it runs, so the map cannot tell which route or template it reaches.',
                spots.dynamic.map((row) => ['<code>' + escapeHtml(row.expression) + '</code>', escapeHtml(DYNAMIC_KINDS[row.kind] || row.kind), at(row)]), 'None.', false)
            + findingGroup('Browser names declared by several scripts', 'Scripts share one global scope, so a reference to one of these names cannot be linked to one script; on a page loading several, the last one wins.',
                spots.sharedNames.map((row) => ['<code>' + escapeHtml(row.name) + '</code>', plural(row.symbols.length, 'script'),
                    row.symbols.map((symbol) => sourceLink(data, symbolFile(symbol), symbolLine(symbol))).join('<br>')]), 'None.')
            + findingGroup('Limits of the method', 'What reading the code cannot establish, whatever the code looks like.',
                (data.code_map.limitations || []).map(escapeHtml), 'None recorded.', false);
    }

    function figuresHtml(context) {
        const codeMap = context.data.code_map;
        const findings = context.findings;
        const figure = (value, label, warn) => '<a class="quality-figure' + (warn && value ? ' quality-figure--warn' : '') + '" href="#'
            + (warn ? 'qualityFindingsTitle' : 'qualityMapTitle') + '"><strong class="quality-figure__value">' + value.toLocaleString('en') + '</strong>'
            + '<span class="quality-figure__label">' + label + '</span></a>';
        return figure(codeMap.modules.length, 'Modules')
            + figure(codeMap.files.length, 'Files')
            + figure(findings.undeclared.length, 'Undeclared dependencies', true)
            + figure(findings.cycles.length, 'Modules depending on each other', true)
            + figure(findings.privateNames.length, 'Private names across a boundary', true);
    }

    function tableHtml(context) {
        const report = context.data.report;
        const ids = Object.keys(report.modules || {}).sort();
        return ids.map((moduleId) => {
            const row = report.modules[moduleId];
            const module = context.modules[moduleId];
            const cells = LANES.map(([lane]) => {
                const summary = laneSummary(row, lane);
                return '<td>' + statusBadge(summary.status, summary.text) + '</td>';
            }).join('');
            return '<tr><th scope="row">' + (module ? moduleButton(moduleId)
                + '<span class="quality-table__repo">' + escapeHtml((REPOSITORIES[module.repository] || {}).label || module.repository) + '</span>' : escapeHtml(moduleId))
                + '</th><td>' + criticalityBadge(row.criticality) + '</td>' + cells + '</tr>';
        }).join('');
    }

    function runStatus(report) {
        if (report.completeness === 'complete') return { tone: 'good', label: 'Complete' };
        if (report.completeness === 'stale') return { tone: 'warn', label: 'Stale' };
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
            : checks.some((check) => check.status === 'stale') ? statusBadge('stale', checks.length + ' checks, stale')
                : statusBadge(passed === checks.length ? 'pass' : 'fail', passed + ' of ' + checks.length + ' passed'))
            + item('App commit', commit('app'))
            + item('Engine commit', commit('engine'))
            + item('Measured', generated && !isNaN(generated) ? escapeHtml(generated.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })) : 'unknown')
            + (data.run_url ? item('Raw evidence', '<a href="' + escapeHtml(data.run_url) + '" target="_blank" rel="noopener noreferrer">CI run <i class="fas fa-external-link-alt" aria-hidden="true"></i></a>') : '');
    }

    function checksHtml(report) {
        const checks = report.checks || [];
        if (!checks.length) return '<p class="quality-empty">No check results recorded.</p>';
        return '<ul class="quality-checks">' + checks.map((check) => '<li><code>' + escapeHtml(check.name) + '</code>' + statusBadge(check.status) + '</li>').join('') + '</ul>';
    }

    function createContext(data, state) {
        const codeMap = data.code_map;
        const moduleLinks = aggregateModuleLinks(codeMap);
        return {
            data, moduleLinks, state,
            modules: indexBy(codeMap.modules, 'id'),
            files: indexBy(codeMap.files, 'id'),
            symbols: indexBy(codeMap.symbols || [], 'id'),
            owners: fileOwners(codeMap),
            findings: boundaryFindings(codeMap, moduleLinks)
        };
    }

    function init(root) {
        const element = (selector) => root.querySelector(selector);
        const state = {
            view: 'modules', focus: null, file: null, colorBy: 'criticality', showUnused: true,
            // The functions map: its colour encoding, the module picked from its list, its line and name switches, and
            // the function to select again when going back to it from a file.
            symbolColorBy: 'module', symbolModule: null, showEdges: true, showLabels: true, from: null, returnTo: null,
            expanded: false, panelOpen: true
        };
        const mapElement = element('#qualityMap');
        const explorer = element('#qualityExplorer');
        const search = element('#qualitySearch');
        const searchResults = element('#qualitySearchResults');
        let context = null;
        let cy = null;
        let hintTimer = null;
        let tooltipTimer = null;
        let tooltipShown = false;
        let matches = [];
        let activeMatch = -1;
        // The selection on the functions map whose names are placed, as ids and the selected dot.
        let symbolFocus = null;

        function setPanel(html) {
            element('#qualityPanel').innerHTML = html;
            element('#qualityPanel').scrollTop = 0;
        }

        function showOverview() {
            if (state.view === 'symbols' && state.symbolModule) setPanel(moduleHtml(context, state.symbolModule));
            else setPanel(overviewHtml(state));
        }

        function selected() {
            return cy ? cy.$(':selected') : null;
        }

        /** The functions map's graph and positions, laid out once on first use. */
        function symbolMap() {
            if (!context.symbolMap) {
                const codeMap = context.data.code_map;
                const graph = symbolGraph(codeMap);
                context.symbolMap = { graph, positions: symbolPositions(codeMap, graph), colors: moduleColors(codeMap), nodes: indexBy(graph.nodes, 'id') };
            }
            return context.symbolMap;
        }

        /**
         * Fades everything but ``target`` and its direct neighbours, and labels the arrows that stay lit. On the
         * functions map the neighbours are also named; without a target, a module picked from the list stays picked out.
         */
        function highlight(target) {
            if (!cy) return;
            const focused = target && target.length;
            const members = focused && target.isNode() ? target.union(target.descendants()) : target;
            const keep = !focused ? null : target.isNode() ? members.closedNeighborhood().union(target.ancestors()) : target.connectedNodes().union(target);
            cy.batch(() => {
                cy.elements().removeClass('faded lit named');
                if (keep) {
                    cy.elements().not(keep).not(keep.ancestors()).addClass('faded');
                    keep.edges().addClass('lit');
                } else if (state.view === 'symbols' && state.symbolModule) {
                    const outside = cy.nodes('.symbol').filter((node) => node.data('module') !== state.symbolModule);
                    outside.addClass('faded');
                    outside.connectedEdges().addClass('faded');
                }
            });
            symbolFocus = keep && state.view === 'symbols'
                ? { ids: new Set(keep.nodes().map((node) => node.id())), first: target.length === 1 ? target.id() : null } : null;
            nameSymbols();
        }

        function select(target) {
            if (!cy) return;
            cy.elements().unselect();
            if (!target || !target.length) {
                highlight(null);
                showOverview();
                return;
            }
            target.select();
            highlight(target);
            // A selection asks for its details, so a hidden panel opens again, keeping the selection in view.
            if (!state.panelOpen) {
                setPanelOpen(true);
                const box = typeof target.renderedBoundingBox === 'function' ? target.renderedBoundingBox() : null;
                if (box && box.x2 > cy.width()) cy.animate({ center: { eles: target } }, { duration: 200 });
            }
            const data = target.data();
            if (data.kind === 'module') setPanel(moduleHtml(context, data.id));
            else if (data.kind === 'module-link') setPanel(moduleLinkHtml(context, context.moduleLinks.find((link) => link.source === data.source && link.target === data.target)));
            else if (data.kind === 'file') setPanel(fileHtml(context, data.id));
            else if (data.kind === 'file-link') setPanel(fileHtml(context, data.source));
            else if (data.kind === 'contract') setPanel(contractHtml(context, data.id));
            else if (data.kind === 'function' || data.kind === 'symbol') setPanel(functionHtml(context, data.id));
            else if (data.kind === 'function-file') setPanel(fileHtml(context, data.id));
            else if (data.kind === 'function-link') {
                // The end in the opened file, which is what the link is listed under.
                const end = [data.target, data.source].find((id) => context.symbols[id] && context.symbols[id].file === state.file);
                setPanel(end ? functionHtml(context, end) : fileHtml(context, state.file));
            } else showOverview();
        }

        /** Brings ``target`` into the middle of the map, for selections made outside it. */
        function reveal(target, zoom) {
            if (!target || !target.length || typeof cy.animate !== 'function') return;
            cy.animate(Object.assign({ center: { eles: target } }, zoom ? { zoom: Math.max(cy.zoom(), zoom) } : {}), { duration: 300, easing: 'ease-in-out-cubic' });
        }

        function crumbsHtml() {
            if (state.view === 'modules') return '<i class="fas fa-sitemap" aria-hidden="true"></i> All modules';
            const separator = '<span class="quality-crumbs__sep" aria-hidden="true"><i class="fas fa-chevron-right"></i></span>';
            const home = '<button type="button" data-view="modules"' + (state.view === 'files' ? ' title="Back to all modules (Esc)"' : '')
                + '><i class="fas fa-arrow-left" aria-hidden="true"></i> All modules</button>' + separator;
            if (state.view === 'symbols') return home + '<span>All functions</span>';
            if (state.view === 'functions' && state.from === 'symbols') {
                return '<button type="button" data-view-toggle="symbols" title="Back to all functions (Esc)"><i class="fas fa-arrow-left" aria-hidden="true"></i> All functions</button>'
                    + separator + '<span>' + escapeHtml(baseName(state.file)) + '</span>';
            }
            if (state.view === 'functions') {
                return home + '<button type="button" data-open-module="' + escapeHtml(state.focus) + '" title="Back to the module\'s files (Esc)">'
                    + escapeHtml(shortName(state.focus)) + '</button>' + separator + '<span>' + escapeHtml(baseName(state.file)) + '</span>';
            }
            return home + '<span>' + (state.focus ? escapeHtml(shortName(state.focus)) : 'All files') + '</span>';
        }

        function setPressed(selector, active) {
            root.querySelectorAll(selector).forEach((button) => {
                const on = active(button);
                button.classList.toggle('is-active', on);
                button.setAttribute('aria-pressed', String(on));
            });
        }

        /** Which of Modules, Files and Functions the current view belongs to. */
        function level() {
            if (state.view === 'symbols' || (state.view === 'functions' && state.from === 'symbols')) return 'symbols';
            return state.view === 'files' && !state.focus ? 'files' : 'modules';
        }

        /** The functions map's module list: colour as on the map, most functions first. */
        function renderExplorer() {
            const list = element('#qualityExplorerModules');
            if (!list) return;
            const map = symbolMap();
            const counts = {};
            map.graph.nodes.forEach((node) => addCount(counts, node.module, 1));
            list.innerHTML = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b)).map((moduleId) => {
                const module = context.modules[moduleId];
                const on = state.symbolModule === moduleId;
                return '<li><button type="button" class="quality-explorer__module' + (on ? ' is-active' : '') + '" data-symbol-module="' + escapeHtml(moduleId)
                    + '" aria-pressed="' + on + '" title="' + escapeHtml(module ? module.title : moduleId) + '">'
                    + '<span class="quality-swatch quality-swatch--dot" style="background:' + nodeColor(module, context.data.report, state.symbolColorBy, map.colors) + '" aria-hidden="true"></span>'
                    + '<span class="quality-explorer__name">' + escapeHtml(shortName(moduleId)) + '</span>'
                    + '<span class="quality-explorer__count">' + counts[moduleId].toLocaleString('en') + '</span></button></li>';
            }).join('');
            const reset = element('#qualityExplorerReset');
            if (reset) reset.disabled = !state.symbolModule && !(selected() && selected().length) && !(search && search.value);
        }

        /**
         * Names the dots whose name is at least LABEL_PX tall at the current zoom and does not cover a name already
         * placed, largest dots first; around a selection, the selection and as many neighbours as fit. Only dots that
         * change are restyled.
         */
        function nameSymbols() {
            if (state.view !== 'symbols' || !cy) return;
            const zoom = cy.zoom();
            const shown = new Map(labelPlaces(symbolMap(), zoom, symbolFocus ? { only: symbolFocus.ids, first: symbolFocus.first } : {}).map((place) => [place.id, place]));
            const name = symbolFocus ? 'named' : 'labelled';
            cy.batch(() => cy.nodes('.symbol').forEach((node) => {
                const place = shown.get(node.id());
                if (place && node.data('labelFont') !== place.font) node.data('labelFont', place.font);
                if (Boolean(place) !== node.hasClass(name)) node.toggleClass(name, Boolean(place));
                if (Boolean(place && place.above) !== node.hasClass('above')) node.toggleClass('above', Boolean(place && place.above));
                if (symbolFocus && node.hasClass('labelled')) node.removeClass('labelled');
            }));
        }

        let naming = false;
        function scheduleNames() {
            if (naming || state.view !== 'symbols') return;
            naming = true;
            global.requestAnimationFrame(() => {
                naming = false;
                nameSymbols();
            });
        }

        /** Applies the Edges and Labels switches to the functions map. */
        function applySymbolSwitches() {
            if (state.view !== 'symbols') return;
            cy.batch(() => {
                cy.edges('.symbol-link').toggleClass('hidden', !state.showEdges);
                cy.nodes('.symbol').toggleClass('unlabelled', !state.showLabels);
            });
        }

        function render() {
            // The module list is a column of the map: showing or hiding it changes the map's width.
            if (explorer && explorer.hidden !== (state.view !== 'symbols')) {
                explorer.hidden = state.view !== 'symbols';
                if (typeof cy.resize === 'function') cy.resize();
            }
            const options = Object.assign({ moduleLinks: context.moduleLinks, symbolMap: state.view === 'symbols' ? symbolMap() : null }, state);
            const build = { modules: moduleElements, files: fileElements, functions: functionElements, symbols: symbolElements }[state.view];
            const elements = build(context.data.code_map, context.data.report, options);
            cy.elements().remove();
            cy.add(elements);
            cy.layout({ name: 'preset', fit: true, padding: state.view === 'symbols' ? 24 : 48 }).run();
            // Open a module close enough to read its file names, and never shrink the module view to unreadable boxes.
            const readable = state.focus ? READABLE_ZOOM : state.view === 'modules' ? MODULE_ZOOM : 0;
            if (readable && typeof cy.zoom === 'function' && cy.zoom() < readable) {
                cy.zoom(readable);
                cy.center(state.focus ? cy.getElementById(state.view === 'functions' ? state.file : state.focus) : undefined);
            }
            element('#qualityLegend').innerHTML = legendHtml(state);
            element('#qualityBreadcrumb').innerHTML = crumbsHtml();
            setPressed('[data-view-toggle]', (button) => button.dataset.viewToggle === level());
            // Colouring by module only exists on the functions map, where the regions need it.
            root.querySelectorAll('[data-color-by="module"]').forEach((button) => { button.hidden = state.view !== 'symbols'; });
            setPressed('[data-color-by]', (button) => button.dataset.colorBy === colorChoice(state));
            element('#qualityUnusedToggle').disabled = state.view !== 'modules';
            if (state.view === 'symbols') {
                applySymbolSwitches();
                renderExplorer();
            }
            if (state.view === 'files' && state.focus) select(cy.getElementById(state.focus));
            else if (state.view === 'functions') setPanel(fileHtml(context, state.file));
            else if (state.view === 'symbols') select(null);
            else showOverview();
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

        function openModule(moduleId) {
            const node = state.view === 'modules' ? cy.getElementById(moduleId) : null;
            const go = () => {
                state.view = 'files';
                state.focus = moduleId;
                state.file = null;
                state.from = null;
                switchView();
            };
            if (node && node.length && typeof cy.animate === 'function') {
                cy.animate({ fit: { eles: node, padding: Math.min(mapElement.clientWidth, mapElement.clientHeight) / 3 } }, { duration: 260, easing: 'ease-in-cubic', complete: go });
            } else {
                go();
            }
        }

        /** Opens one file's functions, and selects ``symbolId`` there when given. From the functions map, Esc goes back to it. */
        function openFile(fileId, symbolId) {
            const chosen = () => {
                if (!symbolId) return;
                select(cy.getElementById(symbolId));
                reveal(cy.getElementById(symbolId));
            };
            if (state.view === 'functions' && state.file === fileId) {
                chosen();
                return;
            }
            if (state.view === 'symbols') {
                state.from = 'symbols';
                state.returnTo = symbolId || null;
            } else if (state.view !== 'functions') {
                state.from = null;
            }
            state.view = 'functions';
            state.focus = context.owners[fileId];
            state.file = fileId;
            switchView(chosen);
        }

        function showModules(selectedId) {
            state.view = 'modules';
            state.focus = null;
            state.file = null;
            state.from = null;
            switchView(() => {
                if (selectedId) select(cy.getElementById(selectedId));
            });
        }

        /** The functions map, with ``symbolId`` selected again when coming back from its file. */
        function showSymbols(symbolId) {
            state.view = 'symbols';
            state.focus = null;
            state.file = null;
            state.from = null;
            switchView(() => {
                if (symbolId && cy.getElementById(symbolId).length) select(cy.getElementById(symbolId));
            });
        }

        /** Picks out one module's functions on the functions map and shows the module in the panel; null clears it. */
        function focusModule(moduleId) {
            state.symbolModule = moduleId;
            cy.elements().unselect();
            highlight(null);
            showOverview();
            renderExplorer();
        }

        /** Selects a function on the functions map and zooms in far enough to read its neighbours' names. */
        function focusSymbol(symbolId) {
            const node = cy.getElementById(symbolId);
            if (!node.length) return;
            select(node);
            reveal(node, FOCUS_ZOOM);
            renderExplorer();
        }

        /** Selects every function of one file on the functions map and shows the file in the panel. */
        function focusFile(fileId) {
            const nodes = cy.nodes('.symbol').filter((node) => context.symbols[node.id()].file === fileId);
            if (!nodes.length) return;
            cy.elements().unselect();
            nodes.select();
            highlight(nodes);
            setPanel(fileHtml(context, fileId));
            if (typeof cy.animate === 'function') {
                cy.animate({ fit: { eles: nodes.closedNeighborhood(), padding: 60 } }, { duration: 300, easing: 'ease-in-out-cubic' });
            }
            renderExplorer();
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
            if (target.isNode()) target.union(target.descendants()).connectedEdges().addClass('hover');
            global.clearTimeout(tooltipTimer);
            // While a tooltip is showing, moving straight to a neighbour shows the neighbour's at once.
            if (tooltipShown) showTooltip(target);
            else tooltipTimer = global.setTimeout(() => showTooltip(target), HOVER_DELAY);
        }

        function hoverEnd() {
            cy.elements('.hover').removeClass('hover');
            global.clearTimeout(tooltipTimer);
            tooltipTimer = global.setTimeout(hideTooltip, TOOLTIP_GRACE);
        }

        function tooltipHtml(target) {
            const data = target.data();
            if (data.kind === 'module' && context.modules[data.id]) {
                const module = context.modules[data.id];
                const coverage = laneSummary((context.data.report.modules || {})[data.id], 'coverage');
                return '<strong>' + escapeHtml(module.title) + '</strong><span>' + escapeHtml(module.criticality) + ' criticality · branch coverage ' + escapeHtml(coverage.text)
                    + ' · ' + plural(moduleLines(context.data.code_map)[data.id] || 0, 'line') + '</span>';
            }
            if (data.kind === 'module-link') {
                const link = context.moduleLinks.find((item) => item.source === data.source && item.target === data.target);
                return '<strong>' + escapeHtml(shortName(link.source)) + ' → ' + escapeHtml(shortName(link.target)) + '</strong><span>'
                    + (link.count ? escapeHtml(kindsText(link.kinds)) : 'No code reference found') + (link.declared ? '' : '<br>Not declared in the catalog') + '</span>';
            }
            if (data.kind === 'file' || data.kind === 'function-file') return '<strong>' + escapeHtml(baseName(data.id)) + '</strong><span>' + escapeHtml(pathOf(data.id)) + '</span>';
            if (data.kind === 'function') {
                const symbol = context.symbols[data.id];
                return '<strong>' + escapeHtml(symbol.name) + '</strong><span>' + escapeHtml(pathOf(symbol.file) + ':' + symbol.line) + '</span>';
            }
            if (data.kind === 'symbol') {
                const node = symbolMap().nodes[data.id];
                return '<strong>' + escapeHtml(node.name) + '</strong><span>' + escapeHtml(pathOf(node.file) + ':' + node.line) + '<br>'
                    + escapeHtml(shortName(node.module)) + ' · used by ' + plural(node.users, 'function or file', 'functions and files') + '</span>';
            }
            if (data.kind === 'file-link' || data.kind === 'function-link') {
                const name = (id) => escapeHtml(context.symbols[id] ? context.symbols[id].name : baseName(id));
                return '<strong>' + name(data.source) + ' → ' + name(data.target) + '</strong><span>' + escapeHtml(data.kinds) + '</span>';
            }
            if (data.kind === 'contract') return '<strong>' + escapeHtml(data.label) + '</strong><span>Contract between the repositories</span>';
            return '';
        }

        function selectLink(key) {
            const go = () => {
                if (!cy.getElementById('link:' + key).length && !state.showUnused) {
                    state.showUnused = true;
                    element('#qualityUnusedToggle').checked = true;
                    render();
                }
                select(cy.getElementById('link:' + key));
                reveal(cy.getElementById('link:' + key));
            };
            if (state.view !== 'modules') {
                state.view = 'modules';
                state.focus = null;
                state.file = null;
                state.from = null;
                switchView(go);
            } else {
                go();
            }
        }

        function scrollToMap() {
            if (!state.expanded) element('#qualityMapSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        function recolor() {
            setPressed('[data-color-by]', (button) => button.dataset.colorBy === colorChoice(state));
            const colors = state.view === 'symbols' ? symbolMap().colors : null;
            cy.batch(() => cy.nodes('.module, .file, .function, .symbol').forEach((node) => {
                const moduleId = node.data('module') || (node.data('kind') === 'module' ? node.id() : node.data('parent'));
                const color = nodeColor(context.modules[moduleId], context.data.report, colorChoice(state), colors);
                node.data(node.data('kind') === 'symbol' ? { color } : paint(color));
            }));
            element('#qualityLegend').innerHTML = legendHtml(state);
            if (state.view === 'symbols') renderExplorer();
        }

        // Search on the functions map: a list of matches under the box, chosen with a click or the arrow keys and Enter.
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
            if (match.kind === 'file') focusFile(match.id);
            else focusSymbol(match.id);
        }

        if (search && searchResults) {
            search.addEventListener('input', () => {
                matches = context ? matchSymbols(symbolMap().graph, search.value) : [];
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
        }

        root.addEventListener('click', (event) => {
            const target = event.target.closest('[data-select-module], [data-select-link], [data-open-module], [data-open-file], [data-select-function], [data-symbol-module], [data-view], [data-view-toggle], [data-color-by], [data-zoom], [data-clear-selection], [data-symbol-reset]');
            if (!target) return;
            event.preventDefault();
            const inPanel = Boolean(target.closest('#qualityPanel'));
            if (target.dataset.selectModule) {
                if (state.view === 'symbols' && inPanel) {
                    focusModule(target.dataset.selectModule);
                } else if (state.view === 'modules') {
                    select(cy.getElementById(target.dataset.selectModule));
                    if (!inPanel) reveal(cy.getElementById(target.dataset.selectModule));
                } else {
                    showModules(target.dataset.selectModule);
                }
                if (!inPanel) scrollToMap();
            } else if (target.dataset.selectLink) {
                selectLink(target.dataset.selectLink);
                if (!inPanel) scrollToMap();
            } else if (target.dataset.openModule) {
                openModule(target.dataset.openModule);
            } else if (target.dataset.openFile) {
                openFile(target.dataset.openFile, target.dataset.openSymbol);
            } else if (target.dataset.selectFunction) {
                const symbol = context.symbols[target.dataset.selectFunction];
                if (symbol && state.view === 'symbols') focusSymbol(symbol.id);
                else if (symbol) openFile(symbol.file, symbol.id);
            } else if (target.dataset.symbolModule) {
                focusModule(state.symbolModule === target.dataset.symbolModule ? null : target.dataset.symbolModule);
            } else if (target.hasAttribute('data-symbol-reset')) {
                if (search) {
                    search.value = '';
                    matches = [];
                    closeMatches();
                }
                focusModule(null);
                if (typeof cy.animate === 'function') cy.animate({ fit: { eles: cy.elements(), padding: 24 } }, { duration: 260, easing: 'ease-in-out-cubic' });
            } else if (target.dataset.view === 'modules' || target.dataset.viewToggle === 'modules') {
                if (state.view !== 'modules') showModules(state.view === 'symbols' ? null : state.focus);
            } else if (target.dataset.viewToggle === 'files') {
                if (state.view === 'files' && !state.focus) return;
                state.view = 'files';
                state.focus = null;
                state.file = null;
                state.from = null;
                switchView();
            } else if (target.dataset.viewToggle === 'symbols') {
                if (state.view !== 'symbols') showSymbols(state.view === 'functions' && state.from === 'symbols' ? state.returnTo : null);
            } else if (target.dataset.colorBy) {
                if (state.view === 'symbols') state.symbolColorBy = target.dataset.colorBy;
                else state.colorBy = target.dataset.colorBy;
                recolor();
            } else if (target.dataset.zoom) {
                zoomBy(target.dataset.zoom === 'in' ? 1.3 : 1 / 1.3);
            } else if (target.hasAttribute('data-clear-selection')) {
                // The panel of a module picked from the list closes by un-picking it.
                if (state.view === 'symbols' && state.symbolModule && !selected().length) focusModule(null);
                else select(null);
                if (state.view === 'symbols') renderExplorer();
            }
        });
        element('#qualityUnusedToggle').addEventListener('change', (event) => {
            state.showUnused = event.target.checked;
            const keep = selected();
            render();
            if (keep && keep.length && keep.isNode()) select(cy.getElementById(keep.id()));
        });
        [['#qualityEdgesToggle', 'showEdges'], ['#qualityLabelsToggle', 'showLabels']].forEach(([selector, key]) => {
            const toggle = element(selector);
            if (!toggle) return;
            toggle.addEventListener('change', () => {
                state[key] = toggle.checked;
                if (cy) applySymbolSwitches();
            });
        });
        element('#qualityFit').addEventListener('click', () => {
            if (cy) cy.animate({ fit: { eles: cy.elements(), padding: state.view === 'symbols' ? 24 : 48 } }, { duration: 260, easing: 'ease-in-out-cubic' });
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
                cy.fit(cy.elements(), state.view === 'symbols' ? 24 : 48);
            }
        }
        if (workspace && expandButton) {
            expandButton.addEventListener('click', () => setExpanded(!state.expanded));
            global.addEventListener('resize', () => {
                if (state.expanded) placeExpanded();
            });
        }

        // The details panel can be hidden to give the map the whole width; selecting something opens it again.
        function setPanelOpen(on) {
            const box = root.querySelector('.quality-workspace');
            const toggle = element('#qualityPanelToggle');
            if (!box || state.panelOpen === on) return;
            state.panelOpen = on;
            box.classList.toggle('is-panel-hidden', !on);
            if (toggle) {
                toggle.setAttribute('aria-pressed', String(on));
                toggle.title = on ? 'Hide the details panel' : 'Show the details panel';
            }
            if (cy) {
                hideTooltip();
                cy.resize();
            }
        }
        const panelToggle = element('#qualityPanelToggle');
        if (panelToggle) panelToggle.addEventListener('click', () => setPanelOpen(!state.panelOpen));

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
            else if (selected().length && !(state.view === 'files' && state.focus && selected().id() === state.focus)) select(null);
            else if (state.view === 'symbols' && state.symbolModule) focusModule(null);
            else if (state.view === 'functions' && state.from === 'symbols') showSymbols(state.returnTo);
            else if (state.view === 'functions') openModule(state.focus);
            else if (state.view === 'files') showModules(state.focus);
            if (state.view === 'symbols') renderExplorer();
        });

        return fetch(root.dataset.apiUrl, { headers: { Accept: 'application/json' } })
            .then((response) => response.json())
            .then((data) => {
                if (!data.available) {
                    element('#qualityUnavailable').hidden = false;
                    return;
                }
                element('#qualityContent').hidden = false;
                if (data.warning) {
                    element('#qualityWarning').hidden = false;
                    element('#qualityWarningText').textContent = data.warning;
                }
                const status = runStatus(data.report);
                const pill = element('#qualityRunStatus');
                if (pill) {
                    pill.className = 'quality-pill quality-pill--' + status.tone;
                    pill.textContent = status.label;
                }
                element('#qualitySummary').innerHTML = summaryHtml(data);
                element('#qualityChecks').innerHTML = checksHtml(data.report);
                if (!data.code_map) {
                    element('#qualityMapSection').hidden = true;
                    element('#qualityFindingsSection').hidden = true;
                    element('#qualityBlindSpotsSection').hidden = true;
                    element('#qualityTable').innerHTML = tableHtml({ data, modules: {} });
                    return;
                }
                context = createContext(data, state);
                element('#qualityTable').innerHTML = tableHtml(context);
                element('#qualityFindings').innerHTML = findingsHtml(context);
                element('#qualityBlindSpots').innerHTML = blindSpotsHtml(context);
                const figures = element('#qualityFigures');
                if (figures) figures.innerHTML = figuresHtml(context);
                cy = global.cytoscape({
                    container: mapElement, style: GRAPH_STYLE, minZoom: 0.15, maxZoom: 10,
                    wheelSensitivity: 0.4, boxSelectionEnabled: false, autoungrabify: true
                });
                // A click focuses: it fades the rest until Esc or a click on the background.
                const selectable = (target) => !target.isParent() || ['module', 'function-file'].includes(target.data('kind'));
                cy.on('tap', (event) => {
                    select(event.target === cy || (event.target.isNode() && !selectable(event.target)) ? null : event.target);
                    if (state.view === 'symbols') renderExplorer();
                });
                cy.on('dbltap', 'node.module', (event) => openModule(event.target.id()));
                cy.on('dbltap', 'node.file', (event) => openFile(event.target.id()));
                cy.on('dbltap', 'node.function, node.function-file.outside, node.symbol', (event) => {
                    const symbol = context.symbols[event.target.id()];
                    openFile(symbol ? symbol.file : event.target.id(), symbol ? symbol.id : undefined);
                });
                const hoverable = 'node.module, node.file-module, node.file, node.contract, node.function, node.function-file, node.symbol, edge';
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
            .catch(() => {
                element('#qualityUnavailable').hidden = false;
            });
    }

    global.QualityDashboard = {
        aggregateModuleLinks,
        boundaryFindings,
        blindSpots,
        moduleLevels,
        modulePositions,
        fileGraph,
        functionGraph,
        symbolGraph,
        symbolSize,
        symbolPositions,
        moduleRing,
        moduleColors,
        packRegions,
        matchSymbols,
        labelPlaces,
        laneSummary,
        nodeColor,
        escapeHtml,
        init
    };

    document.addEventListener('DOMContentLoaded', () => {
        const root = document.getElementById('qualityDashboard');
        if (root) init(root);
    });
})(window);
