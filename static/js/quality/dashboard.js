/**
 * Code quality dashboard: the published report and code map, drawn as an interactive module graph.
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
    const LINK_KINDS = { imports: 'imports', uses: 'names imported or referenced', calls: 'calls', loads: 'script loads' };
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
    // Below this zoom file names are too small to read, so a module opens at least this close.
    const READABLE_ZOOM = 0.8;
    const MODULE_ZOOM = 0.5;

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
            data: { id: 'file-link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'file-link', width: edgeWidth(link.count) / 1.5 }
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
        { selector: 'node.file.entry', style: { 'outline-width': 1.5, 'outline-color': INK, 'outline-opacity': 0.6, 'outline-offset': 2 } },
        { selector: 'node.repository, node.file-module', style: {
            label: 'data(label)', 'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': -8, 'text-transform': 'uppercase',
            'font-size': 12, 'font-weight': 700, color: MUTED, 'background-color': '#f8f9fa', 'background-opacity': 1,
            'border-width': 1, 'border-color': '#e5e7eb', shape: 'round-rectangle', 'corner-radius': 14, padding: 30
        } },
        // File boxes are drawn small when a whole repository fits the screen; a larger name keeps them legible.
        { selector: 'node.file-module', style: { 'font-size': 14, padding: 18 } },
        { selector: 'node.file-module.overview', style: { 'font-size': 30, color: INK, 'text-margin-y': -12 } },
        { selector: 'node.file-module.outside', style: { 'background-color': '#ffffff', 'border-style': 'dashed', 'border-color': '#ced4da' } },
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
        { selector: '.faded', style: { opacity: 0.12 } },
        { selector: 'edge.lit', style: { 'line-opacity': 1, 'z-index': 10 } },
        { selector: 'edge.lit[label]', style: {
            label: 'data(label)', 'font-family': FONT, 'font-size': 11, 'font-weight': 600, color: INK, 'text-rotation': 'none',
            'text-background-color': '#ffffff', 'text-background-opacity': 1, 'text-background-padding': 3, 'text-background-shape': 'round-rectangle',
            'text-border-width': 1, 'text-border-color': '#e5e7eb', 'text-border-opacity': 1
        } },
        { selector: 'node.hover', style: { 'underlay-opacity': 0.14 } },
        { selector: 'node:selected', style: { 'underlay-opacity': 0.3, 'underlay-padding': 6 } },
        { selector: 'edge:selected', style: { 'underlay-color': NAVY, 'underlay-opacity': 0.2, 'underlay-padding': 5 } }
    ];

    function legendHtml(state) {
        const items = [];
        const swatch = (color, label) => '<li><span class="quality-swatch" style="background:' + color + '" aria-hidden="true"></span>' + label + '</li>';
        if (state.colorBy === 'criticality') {
            Object.keys(CRITICALITY).forEach((level) => items.push('<li>' + criticalityBadge(level) + '</li>'));
        } else if (state.colorBy === 'coverage') {
            items.push('<li><span class="quality-ramp" style="background:linear-gradient(90deg,' + COVERAGE_RAMP.join(',') + ')" aria-hidden="true"></span>Branch coverage 0% to 100%</li>');
            items.push(swatch(NOT_MEASURED_COLOR, 'No runtime code or not measured'));
        } else {
            Object.keys(REPOSITORIES).forEach((repository) => items.push(swatch(REPOSITORIES[repository].color, REPOSITORIES[repository].label)));
        }
        items.push('<li class="quality-legend__break" aria-hidden="true"></li>');
        const line = (kind, label) => '<li><span class="quality-line quality-line--' + kind + '" aria-hidden="true"></span>' + label + '</li>';
        if (state.view === 'modules') {
            items.push(line('declared', 'Code dependency the catalog declares'));
            items.push(line('undeclared', 'Code dependency the catalog does not declare'));
            if (state.showUnused) items.push(line('unused', 'Declared, but no code reference found'));
            items.push('<li><span class="quality-swatch quality-swatch--contract" aria-hidden="true"></span>Contract between repositories</li>');
            items.push('<li>Box height: lines of code. Hover an arrow for its code references.</li>');
        } else {
            items.push(line('internal', 'Inside one module'));
            items.push(line('crossing', 'Across a declared module dependency'));
            items.push(line('undeclared', 'Across an undeclared module dependency'));
            items.push('<li><span class="quality-swatch quality-swatch--entry" aria-hidden="true"></span>Ringed: file used from another module</li>');
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
        if (state.view === 'files') {
            return '<p class="quality-eyebrow">' + (state.focus ? 'Module files' : 'All files') + '</p>'
                + '<h2 class="quality-panel__title">How to read the files</h2>'
                + '<ol class="quality-steps">'
                + (state.focus
                    ? '<li>The opened module is in the middle. Modules that use it are on the left, modules it uses on the right.</li>'
                        + '<li>Inside, files are ordered by how far they are from where calls enter the module.</li>'
                    : '<li>Every module\'s files, with the modules in the layers of the module view.</li>')
                + '<li>A ringed file is used from another module: the arrows crossing a border are the module\'s actual interface.</li>'
                + '<li>Hover a file to trace its links; select it for details.</li>'
                + '<li>Press <kbd>Esc</kbd> or use <strong>All modules</strong> at the top left to go back.</li>'
                + '</ol>';
        }
        return '<p class="quality-eyebrow">Module map</p>'
            + '<h2 class="quality-panel__title">How to read the map</h2>'
            + '<ol class="quality-steps">'
            + '<li>Each box is a module: a group of files with one responsibility in the module catalog.</li>'
            + '<li>An arrow goes from the module whose code uses another module to the module it uses. A module sits above the modules it declares, so declared dependencies point down.</li>'
            + '<li>An orange dashed arrow is a code dependency the catalog does not declare.</li>'
            + '<li>Hover a module to trace its dependencies, select it for details, and double-click it to open its files.</li>'
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
            + list(used, 'No function or class is referenced from another module\'s code. Use may go through HTTP, the database or templates, which the map does not see.')
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
            ? 'The catalog declares this dependency, but no code reference was found. It may go through HTTP, the database or templates, which the map does not see.'
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
        return CLOSE_BUTTON
            + '<p class="quality-eyebrow">File in ' + escapeHtml(shortName(file.module)) + '</p>'
            + '<h2 class="quality-panel__title">' + escapeHtml(baseName(fileId)) + '</h2>'
            + '<p>' + sourceLink(context.data, fileId) + '</p>'
            + '<p class="quality-muted">' + plural(file.lines || 0, 'line') + ', ' + plural(file.symbols || 0, 'function or class', 'functions and classes') + '.</p>'
            + '<h3 class="quality-panel__subtitle">Used from other modules (' + used.length + ')</h3>'
            + list(used.map((symbol) => '<code>' + escapeHtml(symbol.name) + '</code><small>by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', ') + '</small>'), 'Nothing in this file.')
            + '<h3 class="quality-panel__subtitle">Uses</h3>' + list(lines(outgoing, 'target'), 'No other file.')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(lines(incoming, 'source'), 'No other file.');
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

    function findingsHtml(context) {
        const findings = context.findings;
        const group = (title, lead, items, empty) => '<div class="quality-finding' + (items.length ? ' quality-finding--warn' : '') + '">'
            + '<div class="quality-finding__head"><h3>' + title + '</h3><span class="quality-finding__count">' + items.length + '</span></div>'
            + '<p>' + lead + '</p>' + list(items, empty) + '</div>';
        const privateItems = findings.privateNames.map((symbol) => ['<code>' + escapeHtml(symbol.name) + '</code> in ' + moduleButton(symbol.module),
            'used by ' + symbol.used_by.map(shortName).map(escapeHtml).join(', '), sourceLink(context.data, symbol.file, symbol.line)]);
        return group('Undeclared module dependencies', 'Code in one module references another module the catalog does not list as a dependency.',
            findings.undeclared.map((link) => [linkButton(link), plural(link.count, 'reference')]), 'None.')
            + group('Modules that depend on each other', 'Each of the two modules references the other, so neither can change in isolation.',
                findings.cycles.map((link) => moduleButton(link.source) + ' ⇄ ' + moduleButton(link.target)), 'None.')
            + group('Private names used across a boundary', 'A name starting with <code>_</code> is internal to its module, but another module uses it.', privateItems, 'None.')
            + group('Declared dependencies without code references', 'These may go through HTTP, the database or templates, which the map does not see, or the declaration is out of date.',
                findings.unused.map(linkButton), 'None.');
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
            owners: fileOwners(codeMap),
            findings: boundaryFindings(codeMap, moduleLinks)
        };
    }

    function init(root) {
        const element = (selector) => root.querySelector(selector);
        const state = { view: 'modules', focus: null, colorBy: 'criticality', showUnused: true };
        const mapElement = element('#qualityMap');
        let context = null;
        let cy = null;
        let hintTimer = null;

        function setPanel(html) {
            element('#qualityPanel').innerHTML = html;
            element('#qualityPanel').scrollTop = 0;
        }

        function showOverview() {
            setPanel(overviewHtml(state));
        }

        function selected() {
            return cy ? cy.$(':selected') : null;
        }

        /** Fades everything but ``target`` and its direct neighbours, and labels the arrows that stay lit. */
        function highlight(target) {
            if (!cy) return;
            cy.batch(() => {
                cy.elements().removeClass('faded lit');
                if (!target || !target.length) return;
                const members = target.isNode() ? target.union(target.descendants()) : target;
                const keep = target.isNode() ? members.closedNeighborhood().union(target.ancestors()) : target.connectedNodes().union(target);
                cy.elements().not(keep).not(keep.ancestors()).addClass('faded');
                keep.edges().addClass('lit');
            });
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

        /** Brings ``target`` into the middle of the map, for selections made outside it. */
        function reveal(target) {
            if (!target || !target.length || typeof cy.animate !== 'function') return;
            cy.animate({ center: { eles: target } }, { duration: 300, easing: 'ease-in-out-cubic' });
        }

        function crumbsHtml() {
            if (state.view === 'modules') return '<i class="fas fa-sitemap" aria-hidden="true"></i> All modules';
            return '<button type="button" data-view="modules" title="Back to all modules (Esc)"><i class="fas fa-arrow-left" aria-hidden="true"></i> All modules</button>'
                + '<span class="quality-crumbs__sep" aria-hidden="true"><i class="fas fa-chevron-right"></i></span>'
                + '<span>' + (state.focus ? escapeHtml(shortName(state.focus)) : 'All files') + '</span>';
        }

        function setPressed(selector, active) {
            root.querySelectorAll(selector).forEach((button) => {
                const on = active(button);
                button.classList.toggle('is-active', on);
                button.setAttribute('aria-pressed', String(on));
            });
        }

        function render() {
            const options = Object.assign({ moduleLinks: context.moduleLinks }, state);
            const elements = state.view === 'modules' ? moduleElements(context.data.code_map, context.data.report, options) : fileElements(context.data.code_map, context.data.report, options);
            cy.elements().remove();
            cy.add(elements);
            cy.layout({ name: 'preset', fit: true, padding: 48 }).run();
            // Open a module close enough to read its file names, and never shrink the module view to unreadable boxes.
            const readable = state.focus ? READABLE_ZOOM : state.view === 'modules' ? MODULE_ZOOM : 0;
            if (readable && typeof cy.zoom === 'function' && cy.zoom() < readable) {
                cy.zoom(readable);
                cy.center(state.focus ? cy.getElementById(state.focus) : undefined);
            }
            element('#qualityLegend').innerHTML = legendHtml(state);
            element('#qualityBreadcrumb').innerHTML = crumbsHtml();
            setPressed('[data-view-toggle]', (button) => button.dataset.viewToggle === (state.view === 'files' && !state.focus ? 'files' : 'modules'));
            element('#qualityUnusedToggle').disabled = state.view !== 'modules';
            if (state.view === 'files' && state.focus) select(cy.getElementById(state.focus));
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
                switchView();
            };
            if (node && node.length && typeof cy.animate === 'function') {
                cy.animate({ fit: { eles: node, padding: Math.min(mapElement.clientWidth, mapElement.clientHeight) / 3 } }, { duration: 260, easing: 'ease-in-cubic', complete: go });
            } else {
                go();
            }
        }

        function showModules(selectedId) {
            state.view = 'modules';
            state.focus = null;
            switchView(() => {
                if (selectedId) select(cy.getElementById(selectedId));
            });
        }

        function zoomBy(factor) {
            if (!cy) return;
            const extent = cy.extent();
            const level = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * factor));
            cy.animate({ zoom: { level, position: { x: (extent.x1 + extent.x2) / 2, y: (extent.y1 + extent.y2) / 2 } } }, { duration: 180 });
        }

        function flashHint() {
            const hint = element('#qualityZoomHint');
            hint.classList.add('is-visible');
            global.clearTimeout(hintTimer);
            hintTimer = global.setTimeout(() => hint.classList.remove('is-visible'), 1400);
        }

        function tooltip(event, html) {
            const box = element('#qualityTooltip');
            if (!html) {
                box.hidden = true;
                return;
            }
            box.innerHTML = html;
            box.hidden = false;
            const width = box.offsetWidth;
            const x = event.renderedPosition.x;
            box.style.left = Math.round(x + 16 + width > mapElement.clientWidth ? Math.max(8, x - 16 - width) : x + 16) + 'px';
            box.style.top = Math.round(event.renderedPosition.y + 16) + 'px';
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
            if (data.kind === 'file') return '<strong>' + escapeHtml(baseName(data.id)) + '</strong><span>' + escapeHtml(pathOf(data.id)) + '</span>';
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
                switchView(go);
            } else {
                go();
            }
        }

        function scrollToMap() {
            element('#qualityMapSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        root.addEventListener('click', (event) => {
            const target = event.target.closest('[data-select-module], [data-select-link], [data-open-module], [data-view], [data-view-toggle], [data-color-by], [data-zoom], [data-clear-selection]');
            if (!target) return;
            event.preventDefault();
            if (target.dataset.selectModule) {
                const inMap = !target.closest('#qualityPanel');
                if (state.view === 'modules') {
                    select(cy.getElementById(target.dataset.selectModule));
                    if (inMap) reveal(cy.getElementById(target.dataset.selectModule));
                } else {
                    showModules(target.dataset.selectModule);
                }
                if (inMap) scrollToMap();
            } else if (target.dataset.selectLink) {
                selectLink(target.dataset.selectLink);
                if (!target.closest('#qualityPanel')) scrollToMap();
            } else if (target.dataset.openModule) {
                openModule(target.dataset.openModule);
            } else if (target.dataset.view === 'modules' || target.dataset.viewToggle === 'modules') {
                if (state.view !== 'modules') showModules(state.focus);
            } else if (target.dataset.viewToggle === 'files') {
                if (state.view === 'files' && !state.focus) return;
                state.view = 'files';
                state.focus = null;
                switchView();
            } else if (target.dataset.colorBy) {
                state.colorBy = target.dataset.colorBy;
                setPressed('[data-color-by]', (button) => button.dataset.colorBy === state.colorBy);
                cy.nodes('.module, .file').forEach((node) => {
                    const moduleId = node.data('kind') === 'module' ? node.id() : node.data('parent');
                    node.data(paint(nodeColor(context.modules[moduleId], context.data.report, state.colorBy)));
                });
                element('#qualityLegend').innerHTML = legendHtml(state);
            } else if (target.dataset.zoom) {
                zoomBy(target.dataset.zoom === 'in' ? 1.3 : 1 / 1.3);
            } else if (target.hasAttribute('data-clear-selection')) {
                select(null);
            }
        });
        element('#qualityUnusedToggle').addEventListener('change', (event) => {
            state.showUnused = event.target.checked;
            const keep = selected();
            render();
            if (keep && keep.length && keep.isNode()) select(cy.getElementById(keep.id()));
        });
        element('#qualityFit').addEventListener('click', () => {
            if (cy) cy.animate({ fit: { eles: cy.elements(), padding: 48 } }, { duration: 260, easing: 'ease-in-out-cubic' });
        });
        // The page scrolls with the wheel: a plain wheel event is stopped before it reaches the map, which then zooms
        // only with Ctrl or ⌘ held (also what a trackpad pinch sends). Touch pinch-zoom is untouched.
        mapElement.parentElement.addEventListener('wheel', (event) => {
            if (!cy) return;
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                return;
            }
            event.stopPropagation();
            flashHint();
        }, { capture: true, passive: false });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape' || !cy || event.target.closest('input, select, textarea')) return;
            if (selected().length && !(state.view === 'files' && state.focus && selected().id() === state.focus)) select(null);
            else if (state.view === 'files') showModules(state.focus);
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
                    element('#qualityTable').innerHTML = tableHtml({ data, modules: {} });
                    return;
                }
                context = createContext(data, state);
                element('#qualityTable').innerHTML = tableHtml(context);
                element('#qualityFindings').innerHTML = findingsHtml(context);
                const figures = element('#qualityFigures');
                if (figures) figures.innerHTML = figuresHtml(context);
                cy = global.cytoscape({
                    container: mapElement, style: GRAPH_STYLE, minZoom: 0.15, maxZoom: 2.5,
                    wheelSensitivity: 0.4, boxSelectionEnabled: false, autoungrabify: true
                });
                cy.on('tap', (event) => select(event.target === cy ? null : event.target.isNode() && event.target.isParent() && event.target.data('kind') !== 'module' ? null : event.target));
                cy.on('dbltap', 'node.module', (event) => openModule(event.target.id()));
                cy.on('mouseover', 'node.module, node.file, node.contract, edge.declared, edge.undeclared, edge.unused', (event) => {
                    mapElement.style.cursor = 'pointer';
                    if (event.target.isNode()) event.target.addClass('hover');
                    if (!selected().length) highlight(event.target);
                    tooltip(event, tooltipHtml(event.target));
                });
                cy.on('mouseout', 'node, edge', (event) => {
                    mapElement.style.cursor = '';
                    event.target.removeClass('hover');
                    if (!selected().length) highlight(null);
                    tooltip(event, null);
                });
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
