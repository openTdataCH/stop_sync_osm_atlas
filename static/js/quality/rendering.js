/**
 * Code quality dashboard, rendering: what the page shows of the code map and of the CI results.
 *
 * The colours, the Cytoscape elements and styles of the map, and the HTML of the legend, the side panel and the
 * sections under the map. Everything is built from a context and returned; nothing here listens to the page.
 */
(function (global) {
    'use strict';

    const {
        FONT, LAYER_GAP, FILE_BUDGET, NAMED_FONT, shortName, repositoryOf, pathOf, baseName, indexBy, drawn,
        symbolFile, symbolLine, addCount, plural, blindSpots, moduleColumns, fileLinks, dotFont, coverageOf
    } = global.QualityMap;

    // Canvas styles cannot read CSS variables: these are the palette values of tokens.css.
    const NAVY = '#174092';
    const GREEN = '#4caf50';
    const PURPLE = '#6b21a8';
    const INK = '#111111';
    const MUTED = '#6c757d';

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
    const ARC = 0.42;
    // A findings card shows this many rows; the rest fold away, so one long list does not set the height of the page.
    const FINDING_ROWS = 6;

    function escapeHtml(value) {
        const replacements = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
        return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, (character) => replacements[character]);
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
        // On Files a line that would run through a third module goes around it instead, on the side the dependency
        // between the two modules takes on Modules. Straight, every such line would run down the middle of the column.
        const columns = moduleColumns(codeMap);
        const owner = Object.fromEntries(view.graph.nodes.map((node) => [node.id, node.module]));
        const around = (link) => {
            const [a, b] = [owner[link.source], owner[link.target]];
            if (state.level !== 'files' || a === b || columns[a] !== columns[b]) return 0;
            const from = view.positions[link.source];
            const to = view.positions[link.target];
            const length = Math.hypot(to.x - from.x, to.y - from.y) || 1;
            const through = view.regions.some((region) => {
                if (region.id === a || region.id === b) return false;
                const along = Math.max(0, Math.min(1, ((region.x - from.x) * (to.x - from.x) + (region.y - from.y) * (to.y - from.y)) / (length * length)));
                return Math.hypot(from.x + along * (to.x - from.x) - region.x, from.y + along * (to.y - from.y) - region.y) < region.r;
            });
            return through ? Math.round((columns[a] ? -1 : 1) * ARC * length) : 0;
        };
        view.graph.links.forEach((link) => {
            const arc = around(link);
            elements.push({
                group: 'edges', classes: 'dot-link ' + (!link.crossing ? 'internal' : link.declared ? 'crossing' : 'crossing undeclared') + (arc ? ' around' : ''),
                data: { id: 'dot-link:' + link.source + '>' + link.target, source: link.source, target: link.target, kind: 'dot-link', kinds: kindsText(link.kinds), arc }
            });
        });
        if (state.level === 'files') {
            (codeMap.clones || []).forEach((clone, index) => {
                if (clone.files[0] === clone.files[1] || !view.positions[clone.files[0]] || !view.positions[clone.files[1]]) return;
                elements.push({ group: 'edges', classes: 'clone', data: { id: 'clone:' + index, source: clone.files[0], target: clone.files[1], kind: 'clone', clone: index } });
            });
        }
        return elements;
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
        { selector: 'edge.dot-link.around', style: { 'curve-style': 'unbundled-bezier', 'control-point-distances': (edge) => edge.data('arc'), 'control-point-weights': 0.5 } },
        // Faded dots drop their names, so the names of the selection and its neighbours stand out.
        { selector: 'node.dot.faded', style: { opacity: 0.16, label: '' } },
        { selector: 'edge.dot-link.faded', style: { opacity: 0.08 } },
        { selector: 'node.dot.named', style: { label: 'data(label)', 'font-size': (node) => node.data('labelFont') || Math.max(node.data('font'), NAMED_FONT), 'z-index': 1000 } },
        { selector: 'node.dot.hover', style: { 'border-width': 1.5, 'border-color': INK, 'underlay-opacity': 0.18 } },
        { selector: 'node:selected', style: { 'underlay-opacity': 0.3, 'underlay-padding': 6 } },
        { selector: 'edge:selected', style: { 'underlay-color': NAVY, 'underlay-opacity': 0.2, 'underlay-padding': 5 } },
        // Lines that have nothing to do with the modules in focus.
        { selector: 'edge.out', style: { display: 'none' } }
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
        const links = fileLinks(codeMap);
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
            + '<h3 class="quality-panel__subtitle">Uses</h3>' + list(ends(links.filter((link) => link.source === fileId), 'target'), 'No other file.')
            + '<h3 class="quality-panel__subtitle">Used by</h3>' + list(ends(links.filter((link) => link.target === fileId), 'source'), 'No other file.')
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

    global.QualityRendering = {
        escapeHtml, nodeColor, laneSummary, kindsText, mapElements, GRAPH_STYLE, legendHtml, HIDE_PANEL_BUTTON,
        CLOSE_BUTTON, overviewHtml, moduleHtml, moduleLinkHtml, modulesHtml, fileHtml, functionHtml, cloneHtml,
        contractHtml, findingsHtml, blindSpotsHtml, cleanupHtml, figuresHtml, tableHtml, runStatus, summaryHtml,
        checksHtml, unavailableHtml
    };
})(window);
