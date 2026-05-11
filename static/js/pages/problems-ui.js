// problems-ui.js - UI rendering and helpers for the Problem Identification Page

/**
 * ProblemsUI - UI rendering, display, and interaction functionality
 * Depends on: ProblemsState, PopupRenderer (from popup-renderer.js)
 */
window.ProblemsUI = (function () {
    'use strict';

    // Small UI helpers
    // Map priority to alert styling
    function getPriorityAlertStyle(priority) {
        const pr = Number(priority);
        if (pr === 1) return { alertClass: 'alert-danger', icon: 'exclamation-circle' };
        if (pr === 2) return { alertClass: 'alert-warning', icon: 'exclamation-triangle' };
        return { alertClass: 'alert-info', icon: 'info-circle' };
    }

    // Serialize data attributes for HTML
    function serializeDataAttrs(attrs) {
        return Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(' ');
    }

    // Wrap content in a problem section item
    function wrapInSection(title, content) {
        return `<div class="problem-section-item"><h6>${title}</h6>${content}</div>`;
    }

    // Extract member display info (badge, identifier, name) with group context awareness
    function getMemberDisplayInfo(member, groupType) {
        const isOsm = groupType === 'osm' ? true : (groupType === 'atlas' ? false : !!member.osm_node_id);
        return {
            badge: `<span class="badge-pill-outline ${isOsm ? 'badge-pill-outline--osm' : 'badge-pill-outline--atlas'}">${isOsm ? 'OSM' : 'ATLAS'}</span>`,
            ident: isOsm ? (member.osm_node_id || '-') : (member.sloid || '-'),
            name: isOsm ? (member.osm_name || member.osm_uic_name || '-')
                : (member.atlas_designation_official || member.atlas_designation || '-'),
            isOsm
        };
    }

    /**
     * Show keyboard shortcuts hint
     */
    function showKeyboardHint() {
        if (!ProblemsState.getKeyboardHintShown()) {
            const hint = $('#keyboardHint');
            hint.addClass('show');
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
        const hint = $('#keyboardHint');
        hint.removeClass('show');
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

        html += `<div class="alert ${alertClass} problem-info-banner mb-3">
                    <small><i class="fas fa-${icon}"></i> ${intent}.</small>
                 </div>`;

        const atlasRows = [
            ['Sloid', problem.sloid || '-']
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
                    <h5>ATLAS</h5>
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

        const atlasOp = (problem.atlas_business_org_abbr || problem.atlas_operator || '').toString().trim().toUpperCase();
        const isSbb = atlasOp === 'SBB';
        const distanceText = problem.distance_m ? `${Math.round(problem.distance_m)} m` : null;

        if (pr === 1) { alertClass = 'alert-danger'; icon = 'exclamation-circle'; }
        else if (pr === 2) { alertClass = 'alert-warning'; icon = 'exclamation-triangle'; }

        switch (problemType) {
            case 'distance': {
                // Map priority to short rationale (do not repeat priority or distance)
                if (pr === 1) intent = `Very large distance${isSbb ? '' : ' and non‑SBB operator'}`;
                else if (pr === 2) intent = `Large distance${isSbb ? '' : ' and non‑SBB operator'}`;
                else intent = isSbb ? 'Distance above 25 m for SBB' : 'Distance above tolerance';
                return `
                    <div class="problem-section-item">
                        <div class="alert ${alertClass} problem-info-banner mb-0">
                            <small><i class="fas fa-${icon}"></i> ${intent}.</small>
                        </div>
                    </div>`;
            }
            case 'unmatched': {
                const isAtlas = problem.stop_type === 'atlas_unmatched';
                const subject = isAtlas ? 'ATLAS entry' : 'OSM entry';
                if (pr === 1) intent = 'No counterpart exists for this UIC or none within 80 m';
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
        return `<div class="problem-section-item"><div class="alert alert-info mb-0"><small><i class="fas fa-info-circle"></i> The matched ATLAS and OSM points are ${distanceText} m apart.</small></div></div>`;
    }

    function generateUnmatchedDetailsHtml(problem) {
        const isAtlas = problem.stop_type === 'atlas_unmatched' || (!!problem.sloid && !problem.osm_node_id);
        return `<div class="problem-section-item"><div class="alert alert-info mb-0"><small><i class="fas fa-info-circle"></i> This ${isAtlas ? 'ATLAS' : 'OSM'} entry has no counterpart under current matching rules.</small></div></div>`;
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
        const atlasRoutes = formatRouteEvidenceItems(problem.routes_atlas, 'atlas');
        const osmRoutes = formatRouteEvidenceItems(problem.routes_osm, 'osm');
        const matchMethod = problem.match_type === 'route_gtfs_direction'
            ? 'direction-name route matching'
            : problem.match_type === 'route_gtfs_tokens'
                ? 'GTFS token route matching'
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

        const atlasRowsHtml = buildRouteRows('Sloid', problem.sloid, atlasRoutes);
        const osmRowsHtml = buildRouteRows('Node ID', problem.osm_node_id, osmRoutes);

        return `
            <div class="problem-section-item">
                <div class="alert alert-warning problem-info-banner mb-3">
                    <small><i class="fas fa-exclamation-triangle"></i> Route evidence conflicts with ${matchMethod}. Review GTFS route IDs, route names and directions.</small>
                </div>
                <div class="attribute-mini-popups">
                    <div class="atlas-match attribute-mini-popup">
                        <h5>ATLAS Routes</h5>
                        <table class="popup-table mb-0">${atlasRowsHtml}</table>
                    </div>
                    <div class="osm-match attribute-mini-popup">
                        <h5>OSM Routes</h5>
                        <table class="popup-table mb-0">${osmRowsHtml}</table>
                    </div>
                </div>
            </div>`;
    }

    function updateFloatingPriority(problem) {
        const badge = $('#problemPriorityDisplay');
        badge.removeClass('d-none problem-meta-chip--p1 problem-meta-chip--p2 problem-meta-chip--p3');

        const pr = Number(problem && problem.priority);
        if (!pr || Number.isNaN(pr)) {
            badge.addClass('d-none').text('');
            return;
        }

        badge.text(`P${pr}`);
        if (pr === 1) badge.addClass('problem-meta-chip--p1');
        else if (pr === 2) badge.addClass('problem-meta-chip--p2');
        else badge.addClass('problem-meta-chip--p3');
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
                const badge = `<span class="badge-pill-outline ${isOsm ? 'badge-pill-outline--osm' : 'badge-pill-outline--atlas'}">${isOsm ? 'OSM' : 'ATLAS'}</span>`;
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
                    const badge = `<span class="badge-pill-outline ${isOsm ? 'badge-pill-outline--osm' : 'badge-pill-outline--atlas'}">${isOsm ? 'OSM' : 'ATLAS'}</span>`;
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
                    const problemId = $(entry.target).data('problem-id');

                    // Find the problem in the current entry's problems
                    const currentEntryProblems = ProblemsState.getCurrentEntryProblems();
                    const newProblemIndex = currentEntryProblems.findIndex(p => p.id === problemId);
                    if (newProblemIndex !== -1 && newProblemIndex !== ProblemsState.getCurrentEntryProblemIndex()) {
                        ProblemsState.setCurrentEntryProblemIndex(newProblemIndex);
                        const problem = currentEntryProblems[newProblemIndex];
                        ProblemsState.setCurrentProblem(problem);

                        // Update map
                        const problemMap = ProblemsState.getProblemMap();
                        const markersLayer = ProblemsState.getProblemMarkersLayer();
                        const linesLayer = ProblemsState.getProblemLinesLayer();

                        if (problemMap && typeof drawProblemOnMap !== 'undefined') {
                            drawProblemOnMap(problemMap, problem, {
                                markersLayer: markersLayer,
                                linesLayer: linesLayer
                            });
                        }

                        // Update active highlight
                        $('.issue-container').removeClass('active');
                        $(entry.target).addClass('active');
                        updateFloatingPriority(problem);


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
        if (isDuplicatesGroupHeader) {
            $('#problemTypeDisplay').text(`Group ${index + 1}/${totalProblems}`);
        } else {
            $('#problemTypeDisplay').text(`Entry ${index + 1}/${totalProblems} · ${problemCount} ${problemText}`);
        }

        // Clear previous content
        const container = $('#actionButtonsContent');
        container.empty();
        const observer = ProblemsState.getObserver();
        if (observer) {
            observer.disconnect();
        }

        // Render all issues for this entry
        currentEntryProblems.forEach((p, i) => {
            const problemHtml = renderSingleProblemUI(p, index, i, currentEntryProblems.length);
            container.append(problemHtml);
        });

        // Setup intersection observer for the new items
        $('.issue-container').each(function () {
            if (observer) {
                observer.observe(this);
            }
        });

        // Set first problem as active
        const firstProblem = currentEntryProblems[0];
        if (firstProblem) {
            // Make first issue active
            $(`.issue-container[data-problem-id="${firstProblem.id}"]`).addClass('active');

            // Draw the problem markers and lines on the map
            const problemMap = ProblemsState.getProblemMap();
            const markersLayer = ProblemsState.getProblemMarkersLayer();
            const linesLayer = ProblemsState.getProblemLinesLayer();

            if (problemMap && typeof drawProblemOnMap !== 'undefined') {
                drawProblemOnMap(problemMap, firstProblem, {
                    markersLayer: markersLayer,
                    linesLayer: linesLayer
                });
            }
            updateFloatingPriority(firstProblem);

            // Load context if enabled
            const showContext = ProblemsState.getShowContext();
            if (showContext && window.ProblemsMap && window.ProblemsMap.loadContextData) {
                window.ProblemsMap.loadContextData(firstProblem);
            } else {
                const contextLayer = ProblemsState.getContextMarkersLayer();
                if (contextLayer) {
                    contextLayer.clearLayers();
                }
            }

            // Add scroll indicator only if the container actually overflows
            const problemContent = $('#actionButtonsContent');
            let scrollIndicator = problemContent.find('.scroll-indicator');
            if (scrollIndicator.length === 0) {
                scrollIndicator = $('<div class="scroll-indicator"><i class="fas fa-chevron-down"></i></div>');
                problemContent.append(scrollIndicator);
            }

            setTimeout(() => {
                const el = problemContent[0];
                if (el && el.scrollHeight > el.clientHeight) {
                    scrollIndicator.addClass('visible');
                } else {
                    scrollIndicator.removeClass('visible');
                }
            }, 100);

            // Hide indicator on scroll
            problemContent.off('scroll.indicator').on('scroll.indicator', () => {
                scrollIndicator.removeClass('visible');
            });
        }
    }

    /**
     * Enable or disable the Previous/Next buttons
     */
    function updateNavButtons() {
        const currentProblemIndex = ProblemsState.getCurrentProblemIndex();
        const currentPage = ProblemsState.getCurrentPage();
        const allProblems = ProblemsState.getAllProblems();
        const totalProblems = ProblemsState.getTotalProblems();
        const problemsByEntry = ProblemsState.getProblemsByEntry();

        // Navigation should be disabled only if we are at the very beginning, or at the very end of ALL problems
        $('#prevProblemBtn').prop('disabled', currentProblemIndex <= 0 && currentPage === 1);
        $('#nextProblemBtn').prop('disabled', allProblems.length === totalProblems && currentProblemIndex >= problemsByEntry.length - 1);
    }

    /**
     * Helper to show a temporary message on the screen
     * Delegates to shared utility
     */
    function showTemporaryMessage(message, type) {
        SharedUtils.showTemporaryMessage(message, type);
    }

    // Public API
    return {
        showKeyboardHint,
        hideKeyboardHint,
        generateAttributeComparisonHtml,
        getMismatchedAttributes,
        updateFloatingPriority,
        renderSingleProblemUI,
        setupIntersectionObserver,
        displayProblem,
        updateNavButtons,
        showTemporaryMessage
    };
})();
