/**
 * Code quality dashboard: the published report and code map, drawn as an interactive module graph.
 *
 * Arrows point from the code that uses to the code it uses. In the module view a module sits above the
 * modules it declares as dependencies, so an arrow pointing upwards goes against the declared layering.
 */
(function (global) {
    'use strict';

    const CRITICALITY = {
        critical: { color: '#0d366b', meaning: 'A defect can publish wrong, incomplete or lost data, or block recovery or deployment.' },
        high: { color: '#1c5cab', meaning: 'A defect shows wrong results or stops data from refreshing, while the published data stays recoverable.' },
        medium: { color: '#3987e5', meaning: 'A defect degrades presentation, documentation or tooling; data and results stay correct.' },
        low: { color: '#86b6ef', meaning: 'A defect is cosmetic or only affects developer convenience.' }
    };
    const REPOSITORIES = {
        engine: { label: 'Matching engine', color: '#eb6834' },
        app: { label: 'Review application', color: '#2a78d6' }
    };
    // Sequential blue, light to dark, for branch coverage in steps of 10%.
    const COVERAGE_RAMP = ['#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];
    const NOT_MEASURED_COLOR = '#d5d8dd';
    // Canvas styles cannot read CSS variables: these match the --color-quality-* tokens in tokens.css.
    const EDGE_COLORS = { declared: '#7d838c', undeclared: '#d9822b', unused: '#b9bec6', internal: '#c9cdd3', crossing: '#2a78d6', contract: '#6250d6' };
    const LINK_KINDS = { imports: 'imports', uses: 'names imported or referenced', calls: 'calls', loads: 'script loads' };
    const STATUS = {
        pass: { label: 'Pass', icon: 'fa-check-circle', tone: 'good' },
        measured: { label: 'Measured', icon: 'fa-chart-bar', tone: 'neutral' },
        fail: { label: 'Fail', icon: 'fa-times-circle', tone: 'bad' },
        attention: { label: 'Needs attention', icon: 'fa-exclamation-triangle', tone: 'warn' },
        invalid: { label: 'Invalid evidence', icon: 'fa-ban', tone: 'bad' },
        stale: { label: 'Stale', icon: 'fa-history', tone: 'muted' },
        not_measured: { label: 'Not measured', icon: 'fa-minus-circle', tone: 'muted' },
        not_applicable: { label: 'Not applicable', icon: 'fa-minus', tone: 'muted' }
    };
    const LANES = [
        ['tests', 'Tests'], ['coverage', 'Branch coverage'], ['mutation', 'Mutation'], ['duplication', 'Duplicated blocks'],
        ['dead_code', 'Python dead code'], ['docs', 'Docs'], ['architecture', 'Architecture']
    ];
    const LEVEL_SPACING = 150;
    const COLUMN_SPACING = 210;
    const REPOSITORY_GAP = 190;
    const FILE_COLUMN_SPACING = 160;
    const FILE_GRID_SPACING = 120;
    const FILE_ROW_SPACING = 52;
    const MAX_FILE_ROWS = 12;
    const BOX_GAP = 80;

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
        codeMap.links.forEach((link) => {
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
        codeMap.links.forEach((link) => connect(owners[link.source], owners[link.target]));
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
        codeMap.links.forEach((link) => {
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

    function moduleLines(codeMap) {
        const lines = {};
        codeMap.files.forEach((file) => addCount(lines, file.module, file.lines || 0));
        return lines;
    }

    function coverageColor(measurement) {
        if (!measurement || typeof measurement.branches !== 'number') return NOT_MEASURED_COLOR;
        return COVERAGE_RAMP[Math.min(COVERAGE_RAMP.length - 1, Math.floor(measurement.branches / 10))];
    }

    function nodeColor(module, report, colorBy) {
        if (colorBy === 'repository') return (REPOSITORIES[module.repository] || {}).color || NOT_MEASURED_COLOR;
        if (colorBy === 'coverage') return coverageColor(((report.modules || {})[module.id] || {}).coverage);
        return (CRITICALITY[module.criticality] || {}).color || NOT_MEASURED_COLOR;
    }

    function edgeWidth(count) {
        return Math.min(10, 1.5 + 1.6 * Math.log2(1 + count));
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

    function statusBadge(status, text) {
        const meta = STATUS[status] || STATUS.not_measured;
        return '<span class="quality-status quality-status--' + meta.tone + '"><i class="fas ' + meta.icon + '" aria-hidden="true"></i>'
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
            data: {
                id: module.id, parent: 'repository:' + module.repository, label: shortName(module.id), kind: 'module',
                size: Math.round(34 + 66 * Math.sqrt((lines[module.id] || 0) / largest)), color: nodeColor(module, report, options.colorBy)
            }
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
        const largest = Math.max(1, ...graph.files.map((file) => file.lines || 0));
        const positions = options.focus ? focusPositions(codeMap, graph, options.focus) : allFilePositions(codeMap, graph);
        const elements = Array.from(new Set(graph.files.map((file) => file.module))).map((moduleId) => ({
            group: 'nodes', classes: 'file-module' + (options.focus && moduleId !== options.focus ? ' outside' : ''),
            data: { id: moduleId, label: shortName(moduleId), kind: 'module' }
        }));
        graph.files.forEach((file) => elements.push({
            group: 'nodes', classes: 'file' + (graph.entries.has(file.id) ? ' entry' : ''), position: positions[file.id],
            data: {
                id: file.id, parent: file.module, label: baseName(file.id), kind: 'file',
                size: Math.round(16 + 34 * Math.sqrt((file.lines || 0) / largest)), color: nodeColor(modules[file.module], report, options.colorBy)
            }
        }));
        graph.links.forEach((link) => elements.push({
            group: 'edges', classes: !link.crossing ? 'internal' : link.declared ? 'crossing' : 'crossing undeclared',
            data: { id: 'file-link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'file-link', width: edgeWidth(link.count) / 1.5 }
        }));
        return elements;
    }

    const GRAPH_STYLE = [
        { selector: 'node', style: { 'font-family': 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', color: '#111111', 'font-size': 12 } },
        { selector: 'node.module, node.file', style: {
            width: 'data(size)', height: 'data(size)', 'background-color': 'data(color)', label: 'data(label)',
            'text-valign': 'bottom', 'text-margin-y': 6, 'text-wrap': 'wrap', 'text-max-width': 150,
            'border-width': 2, 'border-color': '#ffffff'
        } },
        { selector: 'node.module', style: { 'font-size': 13, 'font-weight': 600 } },
        { selector: 'node.file', style: { 'font-size': 10, 'text-max-width': 110, 'min-zoomed-font-size': 7 } },
        { selector: 'node.file.entry', style: { 'border-width': 4, 'border-color': EDGE_COLORS.crossing } },
        { selector: 'node.repository, node.file-module', style: {
            label: 'data(label)', 'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -6, 'font-size': 13, 'font-weight': 700,
            color: '#52514e', 'background-color': '#f6f7f9', 'background-opacity': 1, 'border-width': 1, 'border-color': '#d5d8dd',
            shape: 'round-rectangle', padding: 28
        } },
        { selector: 'node.file-module.outside', style: { 'background-color': '#ffffff', 'border-style': 'dashed' } },
        { selector: 'node.contract', style: {
            shape: 'diamond', width: 26, height: 26, 'background-color': EDGE_COLORS.contract, label: 'data(label)',
            'text-valign': 'bottom', 'text-margin-y': 6, 'text-wrap': 'wrap', 'text-max-width': 120, 'font-size': 11, color: '#52514e'
        } },
        { selector: 'edge', style: {
            width: 'data(width)', 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.9,
            'line-color': EDGE_COLORS.declared, 'target-arrow-color': EDGE_COLORS.declared
        } },
        { selector: 'edge[label]', style: {
            label: 'data(label)', 'font-size': 10, color: '#52514e', 'text-background-color': '#ffffff', 'text-background-opacity': 0.9,
            'text-background-padding': 2, 'text-rotation': 'none'
        } },
        { selector: 'edge.unused', style: { 'line-color': EDGE_COLORS.unused, 'target-arrow-color': EDGE_COLORS.unused, 'line-style': 'dotted' } },
        { selector: 'edge.internal', style: { 'line-color': EDGE_COLORS.internal, 'target-arrow-color': EDGE_COLORS.internal, 'arrow-scale': 0.6 } },
        { selector: 'edge.crossing', style: { 'line-color': EDGE_COLORS.crossing, 'target-arrow-color': EDGE_COLORS.crossing } },
        // After .crossing: an undeclared crossing edge must look undeclared.
        { selector: 'edge.undeclared', style: { 'line-color': EDGE_COLORS.undeclared, 'target-arrow-color': EDGE_COLORS.undeclared, 'line-style': 'dashed', 'line-dash-pattern': [7, 4] } },
        { selector: 'edge.contract-link', style: {
            width: 1.5, 'line-color': EDGE_COLORS.contract, 'line-style': 'dotted', 'target-arrow-shape': 'none', 'curve-style': 'straight'
        } },
        { selector: '.faded', style: { opacity: 0.15 } },
        { selector: 'node:selected', style: { 'border-width': 4, 'border-color': '#d9822b' } },
        { selector: 'edge:selected', style: { 'underlay-color': '#d9822b', 'underlay-opacity': 0.35, 'underlay-padding': 4 } }
    ];

    function legendHtml(state) {
        const items = [];
        if (state.colorBy === 'criticality') {
            Object.keys(CRITICALITY).forEach((level) => items.push('<li>' + criticalityBadge(level) + '</li>'));
        } else if (state.colorBy === 'coverage') {
            items.push('<li><span class="quality-ramp" style="background:linear-gradient(90deg,' + COVERAGE_RAMP.join(',') + ')" aria-hidden="true"></span>Branch coverage 0% to 100%</li>');
            items.push('<li><span class="quality-swatch" style="background:' + NOT_MEASURED_COLOR + '" aria-hidden="true"></span>No runtime code or not measured</li>');
        } else {
            Object.keys(REPOSITORIES).forEach((repository) => items.push('<li><span class="quality-swatch" style="background:' + REPOSITORIES[repository].color + '" aria-hidden="true"></span>' + REPOSITORIES[repository].label + '</li>'));
        }
        const line = (kind, label) => '<li><span class="quality-line quality-line--' + kind + '" aria-hidden="true"></span>' + label + '</li>';
        if (state.view === 'modules') {
            items.push(line('declared', 'Code dependency the catalog declares'));
            items.push(line('undeclared', 'Code dependency the catalog does not declare'));
            if (state.showUnused) items.push(line('unused', 'Declared, but no code reference found'));
            items.push(line('contract', 'Declared contract between repositories'));
            items.push('<li class="quality-legend__note">Size: lines of code. Numbers: code references.</li>');
        } else {
            items.push(line('internal', 'Inside one module'));
            items.push(line('crossing', 'Across a declared module dependency'));
            items.push(line('undeclared', 'Across an undeclared module dependency'));
            items.push('<li><span class="quality-swatch quality-swatch--entry" aria-hidden="true"></span>File used from another module</li>');
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

    function list(items, empty) {
        return items.length ? '<ul class="quality-list">' + items.map((item) => '<li>' + item + '</li>').join('') + '</ul>' : '<p class="quality-muted">' + empty + '</p>';
    }

    function overviewHtml(context) {
        const findings = context.findings;
        return '<h2 class="quality-panel__title">How to read the map</h2>'
            + '<p>Each circle is a module: a group of files with one responsibility in the module catalog. An arrow goes from the module whose code uses another module to the module it uses.</p>'
            + '<p>A module sits above the modules it declares as dependencies, so most arrows point down. An orange dashed arrow is a code dependency the catalog does not declare.</p>'
            + '<p>Select a module or arrow for details. Double-click a module, or use <strong>Open module</strong>, to see its files and the files that enter or leave it.</p>'
            + '<h3 class="quality-panel__subtitle">At a glance</h3>'
            + '<ul class="quality-list">'
            + '<li>' + plural(findings.undeclared.length, 'undeclared module dependency', 'undeclared module dependencies') + '</li>'
            + '<li>' + plural(findings.cycles.length, 'pair of modules', 'pairs of modules') + ' depending on each other</li>'
            + '<li>' + plural(findings.privateNames.length, 'private name') + ' used from another module</li>'
            + '</ul>';
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
            return '<tr><th scope="row">' + label + '</th><td>' + statusBadge(summary.status, summary.text)
                + (summary.detail ? '<div class="quality-muted">' + escapeHtml(summary.detail) + '</div>' : '') + '</td></tr>';
        }).join('');
        const dependencyItem = (link, other) => moduleButton(other) + ' <span class="quality-muted">'
            + (link.count ? plural(link.count, 'reference') : 'no code reference found')
            + (link.declared ? '' : ', <strong class="quality-warn-text">not declared</strong>') + '</span>';
        const entrypoints = module.entrypoints.map((entry) => '<code>' + escapeHtml(entry.entry) + '</code> <span class="quality-muted">'
            + (!entry.symbol ? 'not found in the code' : usedIds.has(entry.symbol) ? 'used from other modules' : 'not referenced by another module\'s code') + '</span>');
        const used = interfaceRows.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code>'
            + (declared.has(symbol.id) ? ' <span class="quality-tag">declared entry point</span>' : '')
            + (/^_[^_]/.test(symbol.name) ? ' <span class="quality-tag quality-tag--warn">private name</span>' : '')
            + '<div class="quality-muted">' + sourceLink(context.data, symbol.file, symbol.line) + ' · used by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', ') + '</div>');
        const docs = Object.keys(module.docs || {}).map((kind) => module.docs[kind].map((path) => escapeHtml(kind) + ': ' + sourceLink(context.data, module.repository + ':' + path)).join('<br>'));
        return '<p class="quality-panel__eyebrow">' + escapeHtml((REPOSITORIES[module.repository] || {}).label || module.repository) + ' module</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(module.title) + '</h2>'
            + '<p><code>' + escapeHtml(module.id) + '</code></p>'
            + '<p>' + escapeHtml(module.responsibility) + '</p>'
            + '<p>' + criticalityBadge(module.criticality) + ' <span class="quality-muted">' + escapeHtml((CRITICALITY[module.criticality] || {}).meaning || '') + '</span></p>'
            + '<button type="button" class="btn btn-sm btn-outline-primary mb-3" data-open-module="' + escapeHtml(module.id) + '"><i class="fas fa-project-diagram" aria-hidden="true"></i> Open module</button>'
            + '<h3 class="quality-panel__subtitle">Evidence</h3><table class="quality-lanes"><tbody>' + lanes + '</tbody></table>'
            + '<h3 class="quality-panel__subtitle">Declared entry points</h3>' + list(entrypoints, 'None declared.')
            + '<h3 class="quality-panel__subtitle">Used from other modules (' + interfaceRows.length + ')</h3>'
            + list(used, 'No function or class is referenced from another module\'s code. Use may go through HTTP, the database or templates, which the map does not see.')
            + '<h3 class="quality-panel__subtitle">Depends on</h3>' + list(outgoing.map((link) => dependencyItem(link, link.target)), 'Nothing.')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(incoming.map((link) => dependencyItem(link, link.source)), 'No other module.')
            + '<h3 class="quality-panel__subtitle">Invariants</h3>' + list(module.invariants.map(escapeHtml), 'None recorded.')
            + '<h3 class="quality-panel__subtitle">Documentation</h3>' + list(docs, 'None declared.')
            + '<p class="quality-muted">Owner: ' + escapeHtml(module.owner) + '. Catalog entry reviewed ' + escapeHtml(module.reviewed) + '.</p>';
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
            ? 'The catalog declares this dependency, but no code reference was found. It may go through HTTP, the database or templates, which the map does not see.'
            : link.declared ? 'The catalog declares this dependency.'
                : '<strong class="quality-warn-text">The catalog does not declare this dependency.</strong> Either declare it in <code>quality/modules.yml</code> or remove the reference.';
        return '<p class="quality-panel__eyebrow">Module dependency</p>'
            + '<h2 class="quality-panel__title">' + moduleButton(link.source) + ' → ' + moduleButton(link.target) + '</h2>'
            + '<p>' + status + '</p>'
            + (link.count ? '<p>' + plural(link.count, 'code reference') + ': ' + escapeHtml(kindsText(link.kinds)) + '.</p>' : '')
            + '<h3 class="quality-panel__subtitle">Names used (' + symbols.length + ')</h3>'
            + list(symbols.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code><div class="quality-muted">' + sourceLink(context.data, symbol.file, symbol.line) + '</div>'), 'Only whole modules or files are referenced.')
            + '<h3 class="quality-panel__subtitle">Files</h3>'
            + list(Object.values(files).map((item) => sourceLink(context.data, item.source) + ' → ' + sourceLink(context.data, item.target)
                + '<div class="quality-muted">' + escapeHtml(kindsText(item.kinds)) + '</div>'), 'None.');
    }

    function fileHtml(context, fileId) {
        const file = context.files[fileId];
        const owners = context.owners;
        const lines = (links, end) => links.map((link) => sourceLink(context.data, link[end]) + (owners[link[end]] !== file.module ? ' <span class="quality-tag">' + escapeHtml(shortName(owners[link[end]])) + '</span>' : '')
            + '<div class="quality-muted">' + escapeHtml(kindsText(link.kinds)) + '</div>');
        const graph = fileGraph(context.data.code_map, file.module);
        const outgoing = graph.links.filter((link) => link.source === fileId);
        const incoming = graph.links.filter((link) => link.target === fileId);
        const used = ((context.data.code_map.interface || {})[file.module] || []).filter((symbol) => symbol.file === fileId);
        return '<p class="quality-panel__eyebrow">File in ' + moduleButton(file.module) + '</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(baseName(fileId)) + '</h2>'
            + '<p>' + sourceLink(context.data, fileId) + '</p>'
            + '<p class="quality-muted">' + plural(file.lines || 0, 'line') + ', ' + plural(file.symbols || 0, 'function or class', 'functions and classes') + '.</p>'
            + '<h3 class="quality-panel__subtitle">Used from other modules (' + used.length + ')</h3>'
            + list(used.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code> <span class="quality-muted">by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', ') + '</span>'), 'Nothing in this file.')
            + '<h3 class="quality-panel__subtitle">Uses</h3>' + list(lines(outgoing, 'target'), 'No other file.')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(lines(incoming, 'source'), 'No other file.');
    }

    function contractHtml(context, contractId) {
        const contract = (context.data.code_map.contracts || []).find((item) => 'contract:' + item.id === contractId);
        return '<p class="quality-panel__eyebrow">Contract</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(contract.title) + '</h2>'
            + '<p><code>' + escapeHtml(contract.id) + '</code></p>'
            + '<p>The repositories do not import each other. They agree on this versioned format instead, and contract tests check both sides.</p>'
            + '<h3 class="quality-panel__subtitle">Produced by</h3>' + list(contract.producers.map(moduleButton), 'Nobody.')
            + '<h3 class="quality-panel__subtitle">Consumed by</h3>' + list(contract.consumers.map(moduleButton), 'Nobody.');
    }

    function findingsHtml(context) {
        const findings = context.findings;
        const privateItems = findings.privateNames.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code> in ' + moduleButton(symbol.module)
            + ' <span class="quality-muted">used by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', ') + ' · ' + sourceLink(context.data, symbol.file, symbol.line) + '</span>');
        return '<div class="quality-findings__group"><h3>Undeclared module dependencies</h3>'
            + '<p class="quality-muted">Code in one module references another module the catalog does not list as a dependency.</p>'
            + list(findings.undeclared.map((link) => linkButton(link) + ' <span class="quality-muted">' + plural(link.count, 'reference') + '</span>'), 'None.') + '</div>'
            + '<div class="quality-findings__group"><h3>Modules that depend on each other</h3>'
            + '<p class="quality-muted">Each of the two modules references the other, so neither can change in isolation.</p>'
            + list(findings.cycles.map((link) => moduleButton(link.source) + ' ⇄ ' + moduleButton(link.target)), 'None.') + '</div>'
            + '<div class="quality-findings__group"><h3>Private names used across a boundary</h3>'
            + '<p class="quality-muted">A name starting with <code>_</code> is internal to its module, but another module uses it.</p>'
            + list(privateItems, 'None.') + '</div>'
            + '<div class="quality-findings__group"><h3>Declared dependencies without code references</h3>'
            + '<p class="quality-muted">These may go through HTTP, the database or templates, which the map does not see, or the declaration is out of date.</p>'
            + list(findings.unused.map(linkButton), 'None.') + '</div>';
    }

    function tableHtml(context) {
        const report = context.data.report;
        const ids = Object.keys(report.modules || {}).sort();
        return ids.map((moduleId) => {
            const row = report.modules[moduleId];
            const cells = LANES.map(([lane]) => {
                const summary = laneSummary(row, lane);
                return '<td>' + statusBadge(summary.status, summary.text) + '</td>';
            }).join('');
            return '<tr><th scope="row">' + (context.modules[moduleId] ? moduleButton(moduleId) : escapeHtml(moduleId)) + '</th><td>'
                + criticalityBadge(row.criticality) + '</td>' + cells + '</tr>';
        }).join('');
    }

    function summaryHtml(data) {
        const report = data.report;
        const revision = report.revision || {};
        const checks = report.checks || [];
        const passed = checks.filter((check) => check.status === 'pass').length;
        const generated = report.generated_at ? new Date(report.generated_at) : null;
        const item = (label, value) => '<div class="quality-summary__item"><dt>' + label + '</dt><dd>' + value + '</dd></div>';
        const commit = (repository) => {
            const sha = revision[repository];
            const base = (data.source_urls || {})[repository];
            if (!sha) return 'unknown';
            const label = '<code>' + escapeHtml(sha.slice(0, 7)) + '</code>';
            return base ? '<a href="' + escapeHtml(base.replace(/\/blob\/[^/]+\/$/, '/commit/' + sha)) + '" target="_blank" rel="noopener noreferrer">' + label + '</a>' : label;
        };
        return item('Evidence', statusBadge(report.completeness === 'complete' ? 'pass' : report.completeness === 'stale' ? 'stale' : 'attention', report.completeness || 'unknown'))
            + item('Required checks', !checks.length ? statusBadge('not_measured')
                : checks.some((check) => check.status === 'stale') ? statusBadge('stale', checks.length + ' checks, stale')
                    : statusBadge(passed === checks.length ? 'pass' : 'fail', passed + ' of ' + checks.length + ' passed'))
            + item('App commit', commit('app'))
            + item('Engine commit', commit('engine'))
            + item('Measured', generated && !isNaN(generated) ? escapeHtml(generated.toLocaleString()) : 'unknown')
            + (data.run_url ? item('Raw evidence', '<a href="' + escapeHtml(data.run_url) + '" target="_blank" rel="noopener noreferrer">CI run</a>') : '');
    }

    function checksHtml(report) {
        return list((report.checks || []).map((check) => statusBadge(check.status) + ' <code>' + escapeHtml(check.name) + '</code>'), 'No check results recorded.');
    }

    function createContext(data) {
        const codeMap = data.code_map;
        const moduleLinks = aggregateModuleLinks(codeMap);
        return {
            data, moduleLinks,
            modules: indexBy(codeMap.modules, 'id'),
            files: indexBy(codeMap.files, 'id'),
            owners: fileOwners(codeMap),
            findings: boundaryFindings(codeMap, moduleLinks)
        };
    }

    function init(root) {
        const element = (selector) => root.querySelector(selector);
        const state = { view: 'modules', focus: null, colorBy: 'criticality', showUnused: true };
        let context = null;
        let cy = null;

        function setPanel(html) {
            element('#qualityPanel').innerHTML = html;
        }

        function showOverview() {
            setPanel(overviewHtml(context));
        }

        function highlight(target) {
            if (!cy) return;
            cy.elements().removeClass('faded');
            if (!target) return;
            const members = target.isNode() ? target.union(target.descendants()) : target;
            const keep = target.isNode() ? members.closedNeighborhood().union(target.ancestors()) : target.connectedNodes().union(target);
            cy.elements().not(keep).not(keep.ancestors()).addClass('faded');
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
            const data = target.data();
            if (data.kind === 'module') setPanel(moduleHtml(context, data.id));
            else if (data.kind === 'module-link') setPanel(moduleLinkHtml(context, context.moduleLinks.find((link) => link.source === data.source && link.target === data.target)));
            else if (data.kind === 'file') setPanel(fileHtml(context, data.id));
            else if (data.kind === 'file-link') setPanel(fileHtml(context, data.source));
            else if (data.kind === 'contract') setPanel(contractHtml(context, data.id));
            else showOverview();
        }

        function render() {
            const options = Object.assign({ moduleLinks: context.moduleLinks }, state);
            const elements = state.view === 'modules' ? moduleElements(context.data.code_map, context.data.report, options) : fileElements(context.data.code_map, context.data.report, options);
            cy.elements().remove();
            cy.add(elements);
            cy.layout({ name: 'preset', fit: true, padding: 40 }).run();
            element('#qualityLegend').innerHTML = legendHtml(state);
            element('#qualityBreadcrumb').innerHTML = state.view === 'modules' ? 'All modules'
                : '<button type="button" class="quality-link" data-view="modules">All modules</button> / ' + (state.focus ? escapeHtml(shortName(state.focus)) + ' files' : 'All files');
            root.querySelectorAll('[data-view-toggle]').forEach((button) => {
                const active = button.dataset.viewToggle === (state.view === 'files' && !state.focus ? 'files' : 'modules');
                button.classList.toggle('active', active);
                button.setAttribute('aria-pressed', String(active));
            });
            element('#qualityUnusedToggle').disabled = state.view !== 'modules';
            if (state.view === 'files' && state.focus) select(cy.getElementById(state.focus));
            else showOverview();
        }

        function openModule(moduleId) {
            state.view = 'files';
            state.focus = moduleId;
            render();
        }

        function showModules(selected) {
            state.view = 'modules';
            state.focus = null;
            render();
            if (selected) select(cy.getElementById(selected));
        }

        function tooltip(event, html) {
            const box = element('#qualityTooltip');
            if (!html) {
                box.hidden = true;
                return;
            }
            box.innerHTML = html;
            box.hidden = false;
            box.style.left = Math.round(event.renderedPosition.x + 14) + 'px';
            box.style.top = Math.round(event.renderedPosition.y + 14) + 'px';
        }

        function tooltipHtml(target) {
            const data = target.data();
            if (data.kind === 'module') {
                const module = context.modules[data.id];
                const coverage = laneSummary((context.data.report.modules || {})[data.id], 'coverage');
                return '<strong>' + escapeHtml(module.title) + '</strong><br>' + escapeHtml(module.criticality) + ' criticality · branch coverage ' + escapeHtml(coverage.text);
            }
            if (data.kind === 'module-link') {
                const link = context.moduleLinks.find((item) => item.source === data.source && item.target === data.target);
                return '<strong>' + escapeHtml(shortName(link.source)) + ' → ' + escapeHtml(shortName(link.target)) + '</strong><br>'
                    + (link.count ? escapeHtml(kindsText(link.kinds)) : 'no code reference found') + (link.declared ? '' : '<br>not declared in the catalog');
            }
            if (data.kind === 'file') return '<strong>' + escapeHtml(pathOf(data.id)) + '</strong><br>' + escapeHtml(shortName(context.owners[data.id]));
            if (data.kind === 'contract') return '<strong>' + escapeHtml(data.label) + '</strong><br>declared contract';
            return '';
        }

        function selectLink(key) {
            if (state.view !== 'modules') showModules();
            if (!cy.getElementById('link:' + key).length && !state.showUnused) {
                state.showUnused = true;
                element('#qualityUnusedToggle').checked = true;
                render();
            }
            select(cy.getElementById('link:' + key));
        }

        root.addEventListener('click', (event) => {
            const target = event.target.closest('[data-select-module], [data-select-link], [data-open-module], [data-view], [data-view-toggle]');
            if (!target) return;
            event.preventDefault();
            if (target.dataset.selectModule) {
                if (state.view === 'modules') select(cy.getElementById(target.dataset.selectModule));
                else showModules(target.dataset.selectModule);
                element('#qualityMap').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else if (target.dataset.selectLink) {
                selectLink(target.dataset.selectLink);
                element('#qualityMap').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else if (target.dataset.openModule) {
                openModule(target.dataset.openModule);
            } else if (target.dataset.view === 'modules' || target.dataset.viewToggle === 'modules') {
                showModules(state.focus);
            } else if (target.dataset.viewToggle === 'files') {
                state.view = 'files';
                state.focus = null;
                render();
            }
        });
        element('#qualityColorBy').addEventListener('change', (event) => {
            state.colorBy = event.target.value;
            const modules = context.modules;
            cy.nodes('.module, .file').forEach((node) => {
                const moduleId = node.data('kind') === 'module' ? node.id() : node.data('parent');
                node.data('color', nodeColor(modules[moduleId], context.data.report, state.colorBy));
            });
            element('#qualityLegend').innerHTML = legendHtml(state);
        });
        element('#qualityUnusedToggle').addEventListener('change', (event) => {
            state.showUnused = event.target.checked;
            render();
        });
        element('#qualityFit').addEventListener('click', () => cy && cy.fit(undefined, 30));

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
                element('#qualitySummary').innerHTML = summaryHtml(data);
                element('#qualityChecks').innerHTML = checksHtml(data.report);
                if (!data.code_map) {
                    element('#qualityMapSection').hidden = true;
                    element('#qualityFindingsSection').hidden = true;
                    element('#qualityTable').innerHTML = tableHtml({ data, modules: {} });
                    return;
                }
                context = createContext(data);
                element('#qualityTable').innerHTML = tableHtml(context);
                element('#qualityFindings').innerHTML = findingsHtml(context);
                cy = global.cytoscape({ container: element('#qualityMap'), style: GRAPH_STYLE, minZoom: 0.2, maxZoom: 3, wheelSensitivity: 0.3, boxSelectionEnabled: false });
                cy.on('tap', (event) => select(event.target === cy ? null : event.target.isNode() && event.target.isParent() && event.target.data('kind') !== 'module' ? null : event.target));
                cy.on('dbltap', 'node.module', (event) => openModule(event.target.id()));
                cy.on('mouseover', 'node.module, node.file, node.contract, edge.declared, edge.undeclared, edge.unused', (event) => tooltip(event, tooltipHtml(event.target)));
                cy.on('mouseout', 'node, edge', (event) => tooltip(event, null));
                cy.on('viewport', () => { element('#qualityTooltip').hidden = true; });
                render();
            })
            .catch(() => {
                element('#qualityUnavailable').hidden = false;
            });
    }

    global.QualityDashboard = {
        aggregateModuleLinks,
        boundaryFindings,
        moduleLevels,
        modulePositions,
        fileGraph,
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
