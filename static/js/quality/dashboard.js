/**
 * Code quality dashboard, the page: loads the evidence of the running commit and runs the map.
 *
 * The three levels are one picture, and one or several modules stay in focus across them. This file keeps that state,
 * answers clicks, the search and the keyboard, and asks code-map.js for positions and rendering.js for what to show.
 */
(function (global) {
    'use strict';

    const {
        shortName, pathOf, baseName, indexBy, fileOwners, addCount, plural, aggregateModuleLinks, boundaryFindings,
        cleanup, moduleHierarchy, symbolGraph, moduleColors, mapView, matchNames, panWithin, labelPlaces,
        moduleLines, coverageOf
    } = global.QualityMap;
    const {
        escapeHtml, nodeColor, laneSummary, kindsText, mapElements, GRAPH_STYLE, legendHtml, HIDE_PANEL_BUTTON,
        CLOSE_BUTTON, overviewHtml, moduleHtml, moduleLinkHtml, modulesHtml, fileHtml, functionHtml, cloneHtml,
        contractHtml, findingsHtml, blindSpotsHtml, cleanupHtml, figuresHtml, tableHtml, runStatus, summaryHtml,
        checksHtml, unavailableHtml
    } = global.QualityRendering;

    const LEVELS = {
        modules: { all: 'All modules', unit: 'lines' },
        files: { all: 'All files', unit: 'files' },
        symbols: { all: 'All functions', unit: 'functions' }
    };

    // A tooltip waits for the cursor to rest, so sweeping across the map shows nothing.
    const HOVER_DELAY = 250;
    const TOOLTIP_GRACE = 120;
    // A dot found by search opens at least this close, where its neighbours' names can be read.
    const FOCUS_ZOOM = 1.6;
    // A module drawn alone fills the map, but a small one opens no closer than this, so its dots stay dots.
    const MODULE_MAX_ZOOM = 3;
    // Names are placed again once a zoom has rested this long: placing them on every frame made zooming stutter.
    const NAME_DELAY = 120;

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
        // The box around everything drawn, which dragging and zooming may not leave.
        let bounds = null;
        let holding = false;

        function keepInView() {
            if (!bounds || holding) return;
            const pan = cy.pan();
            const kept = panWithin(pan, cy.zoom(), bounds, cy.width(), cy.height());
            if (kept.x === pan.x && kept.y === pan.y) return;
            holding = true;
            cy.pan(kept);
            holding = false;
        }

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
                cy.elements().removeClass('faded lit named out');
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
         * The modules in focus stay and every other module fades, also the ones they depend on. The lines lit are the
         * ones that leave a single module, and with several modules the ones from one of them to another. Every other
         * line fades on Modules and is not drawn among dots, where there are hundreds; the lines inside a single
         * module stay as they are.
         */
        function highlightModules() {
            const chosen = new Set(state.modules);
            const single = chosen.size === 1;
            const moduleOf = (node) => (node.data('kind') === 'module' ? node.id() : node.data('module'));
            cy.batch(() => {
                cy.elements().removeClass('faded lit named out');
                cy.nodes('.module, .dot').forEach((node) => {
                    if (!chosen.has(moduleOf(node))) node.addClass('faded');
                });
                cy.edges().forEach((edge) => {
                    const source = moduleOf(cy.getElementById(edge.data('source')));
                    const target = moduleOf(cy.getElementById(edge.data('target')));
                    const touches = chosen.has(source) || chosen.has(target);
                    // A contract hangs on the modules it joins, so it only counts for a single module.
                    const lit = source !== target && (single ? touches : chosen.has(source) && chosen.has(target) && edge.data('kind') !== 'contract-link');
                    if (lit) edge.addClass('lit');
                    else if (!single || !touches) edge.addClass(state.level === 'modules' ? 'faded' : 'out');
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
            bounds = null;
            cy.layout({ name: 'preset', fit: true, padding: fitPadding() }).run();
            bounds = cy.elements().boundingBox();
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
                cy.on('viewport', keepInView);
                cy.on('zoom', scheduleNames);
                render();
            })
            .catch(() => unavailable(null));
    }

    global.QualityDashboard = {
        createContext, init
    };

    document.addEventListener('DOMContentLoaded', () => {
        const root = document.getElementById('qualityDashboard');
        if (root) init(root);
    });
})(window);
