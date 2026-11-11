// problems-ui.js - UI rendering and helpers for the Problem Identification Page

/**
 * ProblemsUI - UI rendering, display, and interaction functionality
 * Depends on: ProblemsState, PopupRenderer (from popup-renderer.js)
 */
window.ProblemsUI = (function () {
    'use strict';

    // Wrap content in a problem section item
    function wrapInSection(title, content) {
        return `<div class="problem-section-item"><h6>${title}</h6>${content}</div>`;
    }

    function renderProblemOnMap(problem) {
        ProblemsMap.renderProblem(problem, { fitView: true });
    }

    // The scroll listener of the current entry's scroll indicator.
    let hideScrollIndicator = null;

    /**
     * Show keyboard shortcuts hint
     */
    function showKeyboardHint() {
        if (!ProblemsState.getKeyboardHintShown()) {
            document.getElementById('keyboardHint').classList.add('show');
            ProblemsState.setKeyboardHintShown(true);

            // Auto-hide after 5 seconds
            const timeout = setTimeout(() => {
                hideKeyboardHint();
            }, 5000);
            ProblemsState.setKeyboardHintTimeout(timeout);
        }
    }

    /**
     * Hide keyboard shortcuts hint
     */
    function hideKeyboardHint() {
        document.getElementById('keyboardHint').classList.remove('show');
        const timeout = ProblemsState.getKeyboardHintTimeout();
        if (timeout) {
            clearTimeout(timeout);
            ProblemsState.setKeyboardHintTimeout(null);
        }
    }

    /**
     * Generate attribute comparison HTML for attributes problems
     */
    function generateAttributeComparisonHtml(problem) {
        let html = '<div class="problem-section-item">';
        const mismatches = getMismatchedAttributes(problem) || [];
        const labels = mismatches.map(m => m.label);
        const pr = Number(problem.priority);
        let alertClass = 'alert-info';
        let icon = 'info-circle';
        let intent = 'Attribute mismatch';

        if (pr === 1) {
            alertClass = 'alert-danger';
            icon = 'exclamation-circle';
            const criticalLabels = labels.filter(l => l === 'UIC Name');
            intent = criticalLabels.length > 0
                ? `Critical attribute mismatch, ${criticalLabels.join(', ')}`
                : 'Critical attribute mismatch';
        } else if (pr === 2) {
            alertClass = 'alert-warning';
            icon = 'exclamation-triangle';
            intent = labels.includes('Local Reference')
                ? 'Attribute mismatch, Local Reference'
                : 'Attribute mismatch';
        } else if (labels.includes('Operator')) {
            intent = 'Attribute mismatch, Operator';
        }

        html += `<div class="alert ${alertClass} problem-info-banner mb-2">
                    <small><i class="fas fa-${icon}"></i> ${intent}.</small>
                 </div>`;

        const atlasRows = [
            [SharedUtils.sourceIdLabelHtml(), problem.sloid || '-']
        ];
        const osmRows = [
            ['Node ID', problem.osm_node_id || '-']
        ];

        if (mismatches.length > 0) {
            mismatches.forEach(attr => {
                atlasRows.push([attr.label, problem[attr.atlas] || '-']);
                osmRows.push([attr.label, problem[attr.osm] || '-']);
            });
        } else {
            atlasRows.push(['Mismatch', 'No details']);
            osmRows.push(['Mismatch', 'No details']);
        }

        const atlasRowsHtml = atlasRows.map(([k, v]) => `<tr><td>${k}:</td><td>${v}</td></tr>`).join('');
        const osmRowsHtml = osmRows.map(([k, v]) => `<tr><td>${k}:</td><td>${v}</td></tr>`).join('');

        html += '<div class="attribute-mini-popups">';
        html += `<div class="atlas-match attribute-mini-popup">
                    <h5>${SharedUtils.sourceLabelHtml()}</h5>
                    <table class="popup-table mb-0">${atlasRowsHtml}</table>
                 </div>`;
        html += `<div class="osm-match attribute-mini-popup">
                    <h5>OSM</h5>
                    <table class="popup-table mb-0">${osmRowsHtml}</table>
                 </div>`;
        html += '</div>';
        html += '</div>';
        return html;
    }

    /**
     * Helper to identify mismatched attributes for display
     */
    function getMismatchedAttributes(problem) {
        const attributesToCheck = [
            { atlas: 'atlas_operator', osm: 'osm_operator', label: 'Operator' },
            { atlas: 'atlas_designation_official', osm: 'osm_uic_name', label: 'UIC Name' },
            { atlas: 'atlas_designation', osm: 'osm_local_ref', label: 'Local Reference' },
            // Transport type comparison removed from attributes problem resolution per requirements
        ];

        const mismatches = [];
        attributesToCheck.forEach(attr => {
            const atlasValue = problem[attr.atlas] || '';
            const osmValue = problem[attr.osm] || '';

            // Consider it a mismatch if values are different
            if (atlasValue !== osmValue) {
                mismatches.push(attr);
            }
        });
        return mismatches;
    }

    /**
     * Generate a concise, priority-aware information banner placed BELOW the action buttons
     */
    function generateProblemInfoBanner(problem) {
        const pr = Number(problem.priority);
        const problemType = problem.problem;
        let intent = '';
        let icon = 'info-circle';
        let alertClass = 'alert-info';

        if (pr === 1) { alertClass = 'alert-danger'; icon = 'exclamation-circle'; }
        else if (pr === 2) { alertClass = 'alert-warning'; icon = 'exclamation-triangle'; }

        switch (problemType) {
            case 'distance': {
                // Map priority to short rationale (do not repeat priority or distance)
                if (pr === 1) intent = 'Very large distance';
                else if (pr === 2) intent = 'Large distance';
                else intent = 'Distance above configured tolerance';
                return `
                    <div class="problem-section-item">
                        <div class="alert ${alertClass} problem-info-banner mb-0">
                            <small><i class="fas fa-${icon}"></i> ${intent}.</small>
                        </div>
                    </div>`;
            }
            case 'unmatched': {
                const isAtlas = problem.stop_type === 'atlas_unmatched';
                const subject = isAtlas ? SharedUtils.sourceLabelHtml() + ' entry' : 'OSM entry';
                if (!SharedUtils.hasCapability('gtfs_identity')) intent = 'No counterpart under the configured matching rules';
                else if (pr === 1) intent = 'No counterpart exists for this UIC or none within 80 m';
                else if (pr === 2) intent = 'No counterpart within 50 m or platform count mismatch for this UIC';
                else intent = 'Unmatched entry requiring review';
                return `
                    <div class="problem-section-item">
                        <div class="alert ${alertClass} problem-info-banner mb-0">
                            <small><i class="fas fa-${icon}"></i> ${subject} is unmatched. ${intent}.</small>
                        </div>
                    </div>`;
            }
            case 'attributes': {
                // Banner is rendered within the attribute comparison section; skip here to avoid duplication
                return '';
            }
            case 'contradicts_route_matching': {
                return '';
            }
            case 'duplicates': {
                // Info is already shown in the resolution actions banner, no need for bottom banner
                return '';
            }
            case 'disused':
            case 'identifier': {
                // Reason and action are rendered together by their details section
                return '';
            }
        }

        // Fallback generic banner
        return `
            <div class="problem-section-item">
                <div class="alert ${alertClass} problem-info-banner mb-0">
                    <small><i class="fas fa-${icon}"></i> Issue detected.</small>
                </div>
            </div>`;
    }

    function generateDistanceDetailsHtml(problem) {
        const distance = problem.distance_m ? Math.round(problem.distance_m) : null;
        const distanceText = distance != null ? `${distance}` : 'unknown';
        return `<div class="problem-section-item"><div class="alert alert-info mb-0"><small><i class="fas fa-info-circle"></i> The matched ${SharedUtils.sourceLabelHtml()} and OSM points are ${distanceText} m apart.</small></div></div>`;
    }

    function generateDisusedDetailsHtml(problem) {
        const source = SharedUtils.sourceLabelHtml();
        const lifecycle = SharedUtils.escapeHtml(problem.osm_lifecycle || 'disused');
        const isConflict = Number(problem.priority) === 1;
        const reason = isConflict
            ? `${source} still lists a stop with the same UIC reference, and that stop has no OSM partner.`
            : 'Apps still treat it as a stop: it keeps an unprefixed stop tag (such as <code>public_transport=platform</code>), or a route relation still lists it.';
        const action = isConflict
            ? `Check on the ground. If the stop is in service, remove the lifecycle prefix in OSM; if it is gone, the ${source} entry is outdated.`
            : 'Prefix or remove the remaining stop tags, and remove the element from route relations that no longer serve it. All its tags are listed in the OSM popup.';
        return `<div class="problem-section-item"><div class="alert ${isConflict ? 'alert-danger' : 'alert-warning'} mb-0"><small><i class="fas fa-${isConflict ? 'exclamation-circle' : 'exclamation-triangle'}"></i> OSM marks this element as <strong>${lifecycle}</strong>. ${reason} ${action}</small></div></div>`;
    }

    // OSM keys that hold the platform identifier; the engine reads the same keys.
    const IDENTIFIER_KEYS = ['ref:sloid', 'railway:ref:sloid'];

    function generateIdentifierDetailsHtml(problem) {
        const idLabel = SharedUtils.sourceIdLabelHtml();
        const source = SharedUtils.sourceLabelHtml();
        const tags = problem.osm_tags || {};
        const rows = IDENTIFIER_KEYS.filter(key => tags[key])
            .map(key => `<tr><td><code>${key}</code></td><td><code>${SharedUtils.escapeHtml(tags[key])}</code></td></tr>`);
        if (problem.sloid) {
            rows.push(`<tr><td>Matched ${source} ${idLabel}</td><td><code>${SharedUtils.escapeHtml(problem.sloid)}</code></td></tr>`);
        }
        const pr = Number(problem.priority);
        const [alertClass, icon, reason, action] = pr === 1
            ? ['alert-danger', 'exclamation-circle',
                `Its ${idLabel} names a ${source} platform more than 150 m away, so matching ignored it.`,
                `It was probably copied from another stop: check which platform this element is, and correct the tag.`]
            : pr === 2
                ? ['alert-warning', 'exclamation-triangle',
                    `Its ${idLabel} names no ${source} platform.`,
                    `It may be outdated or mistyped: look the platform up in ${source} and correct the tag.`]
                : ['alert-info', 'info-circle',
                    `A value is not a ${idLabel}, which has the form <code>ch:1:sloid:…</code>.`,
                    `It may hold another number, such as a UIC code: replace it with the platform's ${idLabel}, or remove it.`];
        return `<div class="problem-section-item"><table class="problem-table mb-2"><tbody>${rows.join('')}</tbody></table>`
            + `<div class="alert ${alertClass} mb-0"><small><i class="fas fa-${icon}"></i> ${reason} ${action}</small></div></div>`;
    }

    function generateUnmatchedDetailsHtml(problem) {
        const isAtlas = problem.stop_type === 'atlas_unmatched' || (!!problem.sloid && !problem.osm_node_id);
        return `<div class="problem-section-item"><div class="alert alert-info mb-0"><small><i class="fas fa-info-circle"></i> This ${isAtlas ? SharedUtils.sourceLabelHtml() : 'OSM'} entry has no counterpart under current matching rules.</small></div></div>`;
    }

    function formatRouteEvidenceItems(routes, sourceType) {
        const uniqueRoutes = [];
        const seen = new Set();

        (Array.isArray(routes) ? routes : []).forEach(route => {
            const baseLabel = sourceType === 'atlas'
                ? (route.route_name_short || route.route_name_long || route.route_id)
                : (route.route_name || route.display_route_id || route.route_id || route.internal_route_id);
            if (!baseLabel) {
                return;
            }

            const routeId = sourceType === 'atlas'
                ? route.route_id
                : (route.display_route_id || route.route_id || route.internal_route_id);
            const normalizedBaseLabel = String(baseLabel);
            const normalizedRouteId = routeId == null ? '' : String(routeId);
            const labelWithId = normalizedRouteId && normalizedBaseLabel !== normalizedRouteId
                ? `${normalizedBaseLabel} (ID: ${normalizedRouteId})`
                : normalizedBaseLabel;
            const directionSuffix = route.direction_id !== undefined && route.direction_id !== null && String(route.direction_id) !== ''
                ? ` Dir: ${route.direction_id}`
                : '';
            const label = `${labelWithId}${directionSuffix}`;

            if (!seen.has(label)) {
                seen.add(label);
                uniqueRoutes.push(label);
            }
        });

        return uniqueRoutes;
    }

    function generateRouteContradictionDetailsHtml(problem) {
        const atlasRoutes = formatRouteEvidenceItems(problem.routes_gtfs, 'atlas');
        const osmRoutes = formatRouteEvidenceItems(problem.routes_osm, 'osm');
        const matchMethod = problem.match_type === 'gtfs_shared_direction'
            ? 'the gtfs_shared_direction match'
            : problem.match_type === 'gtfs_shared_route'
                ? 'the gtfs_shared_route match'
                : 'the current matched pair';

        function buildRouteRows(identifierLabel, identifierValue, routes) {
            const rows = [[identifierLabel, identifierValue || '-']];

            if (!routes.length) {
                rows.push(['Route Evidence', 'No route evidence available']);
            } else {
                routes.forEach((route, index) => {
                    rows.push([`Route ${index + 1}`, route]);
                });
            }

            return rows.map(([key, value]) => `<tr><td>${key}:</td><td>${value}</td></tr>`).join('');
        }

        const atlasRowsHtml = buildRouteRows(SharedUtils.sourceIdLabelHtml(), problem.sloid, atlasRoutes);
        const osmRowsHtml = buildRouteRows('Node ID', problem.osm_node_id, osmRoutes);

        return `
            <div class="problem-section-item">
                <div class="alert alert-warning problem-info-banner mb-2">
                    <small><i class="fas fa-exclamation-triangle"></i> Route evidence conflicts with ${matchMethod}. Compare route names, GTFS route IDs, and directions.</small>
                </div>
                <div class="attribute-mini-popups">
                    <div class="atlas-match attribute-mini-popup">
                        <h5>${SharedUtils.escapeHtml(SharedUtils.routeSourceLabel())} Routes</h5>
                        <table class="popup-table mb-0">${atlasRowsHtml}</table>
                    </div>
                    <div class="osm-match attribute-mini-popup">
                        <h5>OSM Routes</h5>
                        <table class="popup-table mb-0">${osmRowsHtml}</table>
                    </div>
                </div>
            </div>`;
    }

    // Each problem type's label in the Type filter and its section of E4.1 Stop problems.
    const PROBLEM_TYPE_DOCS = {
        attributes: ['Attributes', '/docs/stop_problems#attribute-problems'],
        contradicts_route_matching: ['Contradicts Route Matching', '/docs/stop_problems#contradicts-route-matching-problems'],
        distance: ['Distance', '/docs/stop_problems#distance-problems'],
        duplicates: ['Duplicates', '/docs/stop_problems#duplicate-problems'],
        unmatched: ['Unmatched', '/docs/stop_problems#unmatched-problems'],
        disused: ['Disused OSM', '/docs/stop_problems#disused-problems'],
        identifier: [null, '/docs/stop_problems#identifier-problems']   // "OSM <identifier>", as in the filter
    };

    // The chips naming the active problem's type, which links to its section of
    // the docs, and its priority. Without a problem both are hidden.
    function updateFloatingChips(problem) {
        const typeChip = document.getElementById('problemTypeDocLink');
        const typeDoc = PROBLEM_TYPE_DOCS[problem && problem.problem];
        if (typeChip) {
            typeChip.classList.toggle('d-none', !typeDoc);
            if (typeDoc) {
                const label = typeDoc[0] || `OSM ${SharedUtils.sourceIdLabel()}`;
                typeChip.href = typeDoc[1];
                typeChip.innerHTML = `${SharedUtils.escapeHtml(label)} <i class="fas fa-info-circle" aria-hidden="true"></i>`;
            }
        }

        const badge = document.getElementById('problemPriorityDisplay');
        if (!badge) return;
        badge.classList.remove('d-none', 'problem-meta-chip--p1', 'problem-meta-chip--p2', 'problem-meta-chip--p3');

        const pr = Number(problem && problem.priority);
        if (!pr || Number.isNaN(pr)) {
            badge.classList.add('d-none');
            badge.textContent = '';
            return;
        }

        badge.textContent = `P${pr}`;
        if (pr === 1) badge.classList.add('problem-meta-chip--p1');
        else if (pr === 2) badge.classList.add('problem-meta-chip--p2');
        else badge.classList.add('problem-meta-chip--p3');
    }

    /**
     * Render the UI for a single problem. Returns HTML string.
     */
    function renderSingleProblemUI(problem, entryIndex, issueIndex, totalIssues) {
        const safeId = String(problem.id).replace(/[^a-zA-Z0-9_-]/g, '-');
        let html = `<div class="issue-container" id="issue-${safeId}" data-problem-id="${problem.id}" data-stop-id="${problem.stop_id}">`;

        // Generate action buttons and content based on problem type
        let actionButtonsHtml = '';

        // Handle duplicates differently due to their multi-member structure
        if (problem.problem === 'duplicates') {
            if (!Array.isArray(problem.members) || problem.members.length === 0) {
                // Individual duplicate entry (shown in "All Problems" view)
                const isOsm = !!problem.has_osm_duplicate;
                const badge = `<span class="badge-pill-outline ${isOsm ? 'badge-pill-outline--osm' : 'badge-pill-outline--atlas'}">${isOsm ? 'OSM' : SharedUtils.sourceLabelHtml()}</span>`;
                const ident = isOsm ? (problem.osm_node_id || '-') : (problem.sloid || '-');
                const name = isOsm ? (problem.osm_name || problem.osm_uic_name || '-')
                    : (problem.atlas_designation_official || problem.atlas_designation || '-');
                const coords = isOsm
                    ? (problem.osm_lat && problem.osm_lon ? `${Math.round(problem.osm_lat * 1e5) / 1e5}, ${Math.round(problem.osm_lon * 1e5) / 1e5}` : '-')
                    : (problem.atlas_lat && problem.atlas_lon ? `${Math.round(problem.atlas_lat * 1e5) / 1e5}, ${Math.round(problem.atlas_lon * 1e5) / 1e5}` : '-');

                let infoHtml = '<table class="problem-table mb-2"><thead><tr>' +
                    '<th>Source</th><th>Identifier</th><th>Name</th><th>Coords</th></tr></thead><tbody>';
                infoHtml += `<tr><td>${badge}</td><td>${ident}</td><td>${name}</td><td>${coords}</td></tr>`;
                infoHtml += '</tbody></table>';
                infoHtml += '<div class="mt-2 text-muted" style="font-size: 0.65rem;"><i class="fas fa-info-circle"></i> Part of a duplicates group</div>';

                actionButtonsHtml += wrapInSection(
                    '<i class="fas fa-clone"></i> Duplicate Entry',
                    infoHtml
                );
            } else {
                // Info block for Members
                let html = '<div class="problem-section-item">';
                html += '<h6><i class="fas fa-clone"></i> Duplicates</h6>';

                // Table of members
                html += '<table class="problem-table"><thead><tr>' +
                    '<th>Source</th><th>Identifier</th><th>Name</th><th>Coords</th></tr></thead><tbody>';

                (problem.members || []).forEach(member => {
                    const isOsmGroup = problem.group_type === 'osm';
                    const isOsm = isOsmGroup ? true : (problem.group_type === 'atlas' ? false : !!member.osm_node_id);
                    const badge = `<span class="badge-pill-outline ${isOsm ? 'badge-pill-outline--osm' : 'badge-pill-outline--atlas'}">${isOsm ? 'OSM' : SharedUtils.sourceLabelHtml()}</span>`;
                    const ident = isOsm ? (member.osm_node_id || '-') : (member.sloid || '-');
                    const name = isOsm ? (member.osm_name || member.osm_uic_name || '-')
                        : (member.atlas_designation_official || member.atlas_designation || '-');
                    const coords = isOsm
                        ? (member.osm_lat && member.osm_lon ? `${Math.round(member.osm_lat * 1e5) / 1e5}, ${Math.round(member.osm_lon * 1e5) / 1e5}` : '-')
                        : (member.atlas_lat && member.atlas_lon ? `${Math.round(member.atlas_lat * 1e5) / 1e5}, ${Math.round(member.atlas_lon * 1e5) / 1e5}` : '-');

                    html += `<tr>
                        <td>${badge}</td>
                        <td><code>${ident}</code></td>
                        <td>${name || '-'}</td>
                        <td><span class="text-muted" style="font-size: 0.65rem">${coords}</span></td>
                    </tr>`;
                });

                html += '</tbody></table></div>';
                actionButtonsHtml += html;
            }
        } else if (problem.problem === 'attributes') {
            actionButtonsHtml += generateAttributeComparisonHtml(problem);
        } else if (problem.problem === 'contradicts_route_matching') {
            actionButtonsHtml += generateRouteContradictionDetailsHtml(problem);
        } else if (problem.problem === 'distance') {
            actionButtonsHtml += generateDistanceDetailsHtml(problem);
        } else if (problem.problem === 'unmatched') {
            actionButtonsHtml += generateUnmatchedDetailsHtml(problem);
        } else if (problem.problem === 'disused') {
            actionButtonsHtml += generateDisusedDetailsHtml(problem);
        } else if (problem.problem === 'identifier') {
            actionButtonsHtml += generateIdentifierDetailsHtml(problem);
        }
        html += actionButtonsHtml;

        // Add concise, priority-aware info banner below the resolution actions (except for distance & unmatched which already show an integrated banner)
        if (problem.problem !== 'distance' && problem.problem !== 'unmatched') {
            html += generateProblemInfoBanner(problem);
        }
        html += '</div>'; // close issue-container
        return html;
    }

    /**
     * Setup intersection observer for scroll navigation
     */
    function setupIntersectionObserver() {
        const options = {
            root: document.getElementById('actionButtonsContent'),
            rootMargin: '0px',
            threshold: 0.6, // Use a slightly lower threshold
        };

        const observer = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const problemId = entry.target.dataset.problemId;

                    // Find the problem in the current entry's problems
                    const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
                    const newProblemIndex = currentEntryProblems.findIndex(p => p.id === problemId);
                    if (newProblemIndex !== -1 && newProblemIndex !== ProblemsState.getCurrentEntryProblemIndex()) {
                        ProblemsState.setCurrentEntryProblemIndex(newProblemIndex);
                        const problem = currentEntryProblems[newProblemIndex];
                        ProblemsState.setCurrentProblem(problem);

                        renderProblemOnMap(problem);

                        // Context is fixed around the active issue, so switching to
                        // another issue in the same entry requires a fresh request.
                        if (ProblemsState.getShowContext()) {
                            ProblemsMap.loadContextData(problem);
                        }

                        // Update active highlight
                        document.querySelectorAll('.issue-container').forEach(item => item.classList.remove('active'));
                        entry.target.classList.add('active');
                        updateFloatingChips(problem);


                    }
                }
            });
        }, options);

        ProblemsState.setObserver(observer);
    }

    /**
     * Display a problem by its index in the problemsByEntry array
     */
    function displayProblem(index) {
        const problemsByEntry = ProblemsState.getProblemsByEntry();
        const totalProblems = ProblemsState.getTotalProblems();

        if (index < 0 || index >= problemsByEntry.length) {
            return;
        }

        ProblemsState.setCurrentProblemIndex(index);
        const currentEntryProblems = problemsByEntry[index];
        ProblemsState.setCurrentEntryProblems(currentEntryProblems);
        ProblemsState.setCurrentEntryProblemIndex(0); // Reset to the first issue
        ProblemsState.setCurrentProblem(currentEntryProblems[0]);

        // Update main header
        const problemCount = currentEntryProblems.length;
        const problemText = problemCount > 1 ? 'Problems' : 'Problem';
        const firstProblemForHeader = currentEntryProblems[0];
        const isDuplicatesGroupHeader = firstProblemForHeader && firstProblemForHeader.problem === 'duplicates';
        const entryNumber = ProblemsData.entryNumber(index);
        const typeDisplay = document.getElementById('problemTypeDisplay');
        if (isDuplicatesGroupHeader) {
            typeDisplay.textContent = `Group ${SharedUtils.formatCount(entryNumber)} of ${SharedUtils.formatCount(totalProblems)}`;
        } else {
            typeDisplay.textContent = `Entry ${SharedUtils.formatCount(entryNumber)} of ${SharedUtils.formatCount(totalProblems)} · ${problemCount} ${problemText}`;
        }
        ProblemsPermalink.sync();

        // Clear previous content
        const container = document.getElementById('actionButtonsContent');
        container.innerHTML = '';
        const observer = ProblemsState.getObserver();
        if (observer) {
            observer.disconnect();
        }

        // Render all issues for this entry
        currentEntryProblems.forEach((p, i) => {
            const problemHtml = renderSingleProblemUI(p, index, i, currentEntryProblems.length);
            container.insertAdjacentHTML('beforeend', problemHtml);
        });

        // Setup intersection observer for the new items
        if (observer) {
            document.querySelectorAll('.issue-container').forEach(item => observer.observe(item));
        }

        // Set first problem as active
        const firstProblem = currentEntryProblems[0];
        if (firstProblem) {
            // Make first issue active
            const firstItem = document.querySelector(`.issue-container[data-problem-id="${firstProblem.id}"]`);
            if (firstItem) firstItem.classList.add('active');

            // Draw after fitting the final view so marker labels and projected
            // overlap offsets use the correct zoom.
            renderProblemOnMap(firstProblem);
            updateFloatingChips(firstProblem);

            // Load context if enabled
            if (ProblemsState.getShowContext()) {
                ProblemsMap.loadContextData(firstProblem);
            } else {
                ProblemsMap.clearContextData();
            }

            // Add scroll indicator only if the container actually overflows
            const scrollIndicator = SharedUtils.element('div', 'scroll-indicator');
            scrollIndicator.innerHTML = '<i class="fas fa-chevron-down"></i>';
            container.appendChild(scrollIndicator);

            setTimeout(() => {
                scrollIndicator.classList.toggle('visible', container.scrollHeight > container.clientHeight);
            }, 100);

            // Hide indicator on scroll
            if (hideScrollIndicator) container.removeEventListener('scroll', hideScrollIndicator);
            hideScrollIndicator = () => scrollIndicator.classList.remove('visible');
            container.addEventListener('scroll', hideScrollIndicator);
        }
    }

    /**
     * Enable or disable the Previous/Next buttons
     */
    function updateNavButtons() {
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const problemsByEntry = ProblemsState.getProblemsByEntry();

        // Disabled only at the very beginning or the very end of the whole
        // list; a permalink can load a window that starts on a later page.
        document.getElementById('prevProblemBtn').disabled = currentProblemIndex <= 0 && ProblemsState.getFirstLoadedPage() === 1;
        document.getElementById('nextProblemBtn').disabled = !ProblemsData.hasMorePages() && currentProblemIndex >= problemsByEntry.length - 1;
    }

    // Public API
    return {
        showKeyboardHint,
        hideKeyboardHint,
        generateAttributeComparisonHtml,
        getMismatchedAttributes,
        updateFloatingChips,
        renderSingleProblemUI,
        setupIntersectionObserver,
        displayProblem,
        updateNavButtons
    };
})();
