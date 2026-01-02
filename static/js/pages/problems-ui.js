// problems-ui.js - UI rendering and helpers for the Problem Identification Page

/**
 * ProblemsUI - UI rendering, display, and interaction functionality
 * Depends on: ProblemsState, PopupRenderer (from popup-renderer.js)
 */
window.ProblemsUI = (function () {
    'use strict';

    // Small UI helpers
    function isSolutionSelected(problem, expected) {
        if (!problem || !problem.solution) return false;
        return String(problem.solution).trim().toLowerCase() === String(expected).trim().toLowerCase();
    }

    function buildSolutionBtnClass(style, active) {
        // Match duplicates style: outline by default, filled when active, always small
        return `btn btn-sm ${active ? 'btn-' + style : 'btn-outline-' + style} professional-button solution-btn`;
    }

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
            badge: `<span class="badge badge-secondary">${isOsm ? 'OSM' : 'ATLAS'}</span>`,
            ident: isOsm ? (member.osm_node_id || '-') : (member.sloid || '-'),
            name: isOsm ? (member.osm_name || member.osm_uic_name || '-')
                : (member.atlas_designation_official || member.atlas_designation || '-'),
            isOsm
        };
    }

    /**
     * Generate common solution status section HTML
     */
    function generateSolutionStatusSection(problem, clearButtonDataAttrs = {}) {
        if (!problem.solution || problem.solution.trim() === '') {
            return '';
        }

        let persistenceHtml = '';
        if (problem.is_persistent) {
            persistenceHtml = `
                <div class="mt-2">
                    <span class="badge badge-success"><i class="fas fa-database"></i> Persistent Solution</span>
                    <small class="text-muted ml-2">This solution will be automatically applied after data imports</small>
                </div>
            `;
        } else {
            const makePeristentAttrs = serializeDataAttrs(clearButtonDataAttrs);
            persistenceHtml = `
                <div class="mt-2">
                    <button class="btn btn-sm btn-outline-success make-persistent-btn" ${makePeristentAttrs}>
                        <i class="fas fa-thumbtack"></i> Make Persistent
                    </button>
                    <small class="text-muted ml-2">Save this solution for future data imports</small>
                </div>
            `;
        }

        const clearButtonAttrs = serializeDataAttrs(clearButtonDataAttrs);

        return `
            <div class="problem-section-item solution-status-section">
                <h6><i class="fas fa-check-circle text-success"></i> Current Solution</h6>
                <div class="alert alert-success solution-display">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>Proposed Solution:</strong> ${problem.solution}
                            <br><small class="text-muted">You can modify this solution by selecting a new action below.</small>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary clear-solution-btn" ${clearButtonAttrs}>
                            <i class="fas fa-undo"></i> Clear
                        </button>
                    </div>
                    ${persistenceHtml}
                </div>
            </div>
        `;
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
        html += '<h6><i class="fas fa-exchange-alt"></i> Attribute Comparison</h6>';
        // Priority-aware concise info banner for attributes, shown above the popups
        (function () {
            const pr = Number(problem.priority);
            let alertClass = 'alert-info';
            let icon = 'info-circle';
            let intent = '';
            // Derive concrete mismatches from available fields
            const mismatches = getMismatchedAttributes(problem) || [];
            const labels = mismatches.map(m => m.label);

            if (pr === 1) {
                alertClass = 'alert-danger';
                icon = 'exclamation-circle';
                // Prefer explicit labels for critical category (UIC number or official name)
                const criticalLabels = labels.filter(l => l === 'UIC Name');
                if (criticalLabels.length > 0) {
                    intent = `Critical attribute mismatch, ${criticalLabels.join(', ')}`;
                } else {
                    // Fallback if we cannot detect specific label on the frontend
                    intent = 'Critical attribute mismatch';
                }
            } else if (pr === 2) {
                alertClass = 'alert-warning';
                icon = 'exclamation-triangle';
                if (labels.includes('Local Reference')) {
                    intent = 'Local reference differs between ATLAS and OSM';
                } else {
                    intent = 'Attribute mismatch';
                }
            } else {
                alertClass = 'alert-info';
                icon = 'info-circle';
                if (labels.includes('Operator')) {
                    intent = 'Operator differs between ATLAS and OSM';
                } else {
                    intent = 'Attribute mismatch';
                }
            }

            html += `<div class="alert ${alertClass} problem-info-banner mb-3">
                        <small><i class="fas fa-${icon}"></i> ${intent}.</small>
                     </div>`;
        })();
        html += '<div class="row">';

        // ATLAS column
        html += '<div class="col-md-6">';
        html += '<h6 class="text-info mb-3"><i class="fas fa-map-marker-alt"></i> ATLAS Entry</h6>';
        if (typeof PopupRenderer !== 'undefined') {
            // Create a temporary ATLAS data object
            const atlasData = {
                sloid: problem.sloid,
                atlas_lat: problem.atlas_lat,
                atlas_lon: problem.atlas_lon,
                atlas_business_org_abbr: problem.atlas_business_org_abbr,
                atlas_designation_official: problem.atlas_designation_official,
                atlas_designation: problem.atlas_designation,
                stop_type: problem.stop_type,
                uic_ref: problem.uic_ref,
                match_type: problem.match_type
            };
            // Add any other atlas_ prefixed properties from problem that might be needed
            Object.keys(problem).forEach(key => {
                if (key.startsWith('atlas_')) {
                    if (!atlasData.hasOwnProperty(key)) {
                        atlasData[key] = problem[key];
                    }
                }
            });
            html += PopupRenderer.generatePopupHtml(atlasData, 'atlas', { hideRoutesAndNotes: true });
        } else {
            html += '<div class="alert alert-warning">ATLAS info not available</div>';
        }
        html += '</div>';

        // OSM column
        html += '<div class="col-md-6">';
        html += '<h6 class="text-primary mb-3"><i class="fas fa-map"></i> OSM Entry</h6>';

        if (typeof PopupRenderer !== 'undefined') {
            // Create a temporary OSM data object
            const osmData = {
                osm_node_id: problem.osm_node_id,
                osm_lat: problem.osm_lat,
                osm_lon: problem.osm_lon,
                osm_operator: problem.osm_operator,
                osm_name: problem.osm_name,
                osm_local_ref: problem.osm_local_ref,
                osm_public_transport: problem.osm_public_transport,
                stop_type: problem.stop_type,
                uic_ref: problem.uic_ref,
                match_type: problem.match_type
            };
            // Add all osm_ prefixed properties from problem
            Object.keys(problem).forEach(key => {
                if (key.startsWith('osm_')) {
                    osmData[key] = problem[key];
                }
            });
            html += PopupRenderer.generatePopupHtml(osmData, 'osm', { hideRoutesAndNotes: true });
        } else {
            html += '<div class="alert alert-warning">OSM info not available</div>';
        }
        html += '</div>';

        html += '</div>'; // End row
        html += '</div>'; // End problem-section-item

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
     * Generate action buttons for distance problems
     */
    function generateDistanceActionButtons(problem) {
        const distanceText = problem.distance_m ? `${Math.round(problem.distance_m)} m` : 'unknown';
        const pr = Number(problem.priority);
        const atlasOp = (problem.atlas_business_org_abbr || problem.atlas_operator || '').toString().trim().toUpperCase();
        const isSbb = atlasOp === 'SBB';
        let alertClass = 'alert-info';
        let rationale = '';
        if (pr === 1) { alertClass = 'alert-danger'; rationale = `Very large distance${isSbb ? '' : ' and non‑SBB operator'}`; }
        else if (pr === 2) { alertClass = 'alert-warning'; rationale = `Large distance${isSbb ? '' : ' and non‑SBB operator'}`; }
        else { alertClass = 'alert-info'; rationale = isSbb ? 'Distance above 25 m for SBB' : 'Distance above tolerance'; }

        // Determine active states for outline-to-filled style
        const atlasActive = isSolutionSelected(problem, 'Atlas correct');
        const osmActive = isSolutionSelected(problem, 'OSM correct');
        const bothActive = isSolutionSelected(problem, 'Both correct');
        const notMatchActive = isSolutionSelected(problem, 'Not a match');

        return `
            <div class="problem-section-item">
                <h6><i class="fas fa-tools"></i> Resolution Actions</h6>
                <div class="alert ${alertClass}">
                    <small><i class="fas fa-info-circle"></i> Distance between ATLAS and OSM: ${distanceText}. ${rationale}. Choose which location is correct.</small>
                </div>
                <div class="d-flex flex-wrap gap-2">
                    <button class="${buildSolutionBtnClass('success', atlasActive)}" data-solution="Atlas correct">
                        <i class="fas fa-check-circle"></i> Atlas correct
                    </button>
                    <button class="${buildSolutionBtnClass('primary', osmActive)}" data-solution="OSM correct">
                        <i class="fas fa-check-circle"></i> OSM correct
                    </button>
                    <button class="${buildSolutionBtnClass('warning', bothActive)}" data-solution="Both correct">
                        <i class="fas fa-pause-circle"></i> Both correct
                    </button>
                    <button class="${buildSolutionBtnClass('danger', notMatchActive)}" data-solution="Not a match">
                        <i class="fas fa-times-circle"></i> Not a match
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Generate action buttons for isolated problems
     */
    function generateIsolatedActionButtons(problem) {
        const pr = Number(problem.priority);
        const isAtlas = problem.stop_type === 'unmatched';
        const subject = isAtlas ? 'ATLAS entry' : 'OSM entry';
        const { alertClass, icon } = getPriorityAlertStyle(pr);

        let intent = '';
        if (pr === 1) intent = 'No counterpart exists for this UIC or none within 80 m';
        else if (pr === 2) intent = 'No counterpart within 50 m or platform count mismatch for this UIC';
        else intent = 'Unmatched entry requiring review';

        // Determine active states
        const shouldDeleteActive = isSolutionSelected(problem, 'Should be deleted');
        const missingOtherActive = isAtlas ? isSolutionSelected(problem, 'Missing OSM') : isSolutionSelected(problem, 'Missing ATLAS');

        // Build button list based on type
        const matchAction = isAtlas ? 'manual-match-atlas' : 'manual-match-osm';
        const missingLabel = isAtlas ? 'Missing OSM' : 'Missing ATLAS';

        if (isAtlas || problem.stop_type === 'osm') {
            const buttonsHtml = `
                <div class="d-flex flex-wrap gap-2">
                    <button class="btn btn-secondary professional-button" data-action="${matchAction}">Match to</button>
                    <button class="${buildSolutionBtnClass('danger', shouldDeleteActive)}" data-solution="Should be deleted">
                        <i class="fas fa-trash"></i> Should be deleted
                    </button>
                    <button class="${buildSolutionBtnClass('info', missingOtherActive)}" data-solution="${missingLabel}">
                        <i class="fas fa-plus-circle"></i> ${missingLabel}
                    </button>
                </div>
            `;
            return wrapInSection(
                '<i class="fas fa-tools"></i> Resolution Actions',
                `<div class="alert ${alertClass}"><small><i class="fas fa-${icon}"></i> ${subject} is unmatched. ${intent}.</small></div>${buttonsHtml}`
            );
        }

        // Fallback for unexpected cases
        return wrapInSection(
            '<i class="fas fa-exclamation-triangle text-danger"></i> Data Inconsistency',
            `<div class="alert alert-danger">This entry is flagged with an 'unmatched' problem, but its type is <code>${problem.stop_type || 'undefined'}</code>, which is not expected for this problem type. Please report this issue.</div>`
        );
    }

    /**
     * Generate action buttons for attributes problems
     */
    function generateAttributesActionButtons(problem) {
        let html = '<div class="problem-section-item">';
        html += '<h6><i class="fas fa-tools"></i> Resolution Actions</h6>';

        const mismatches = getMismatchedAttributes(problem);
        let solution = {};
        if (problem.solution && problem.solution.trim() !== '' && problem.solution.trim().startsWith('{')) {
            try {
                solution = JSON.parse(problem.solution);
            } catch (e) {
                console.error("Error parsing solution JSON:", e);
                solution = {};
            }
        } else if (problem.solution) {
            // Handle legacy string solutions
            html += `<div class="alert alert-warning"><strong>Legacy Solution:</strong> ${problem.solution}</div>`;
        }

        if (mismatches.length > 0) {
            html += '<p><small><i class="fas fa-info-circle"></i> For each mismatched attribute, choose the correct source.</small></p>';
            html += '<table class="table table-sm attribute-resolution-table"><tbody>';

            mismatches.forEach(attr => {
                const atlasValue = problem[attr.atlas] || '<em>(empty)</em>';
                const osmValue = problem[attr.osm] || '<em>(empty)</em>';
                const resolvedValue = solution[attr.label];

                html += `<tr>
                    <td><strong>${attr.label}</strong></td>
                    <td class="attribute-value">${atlasValue}</td>
                    <td class="attribute-value">${osmValue}</td>
                    <td class="attribute-action">`;

                if (resolvedValue !== undefined) {
                    html += `<div class="text-success"><i class="fas fa-check-circle"></i> <strong>${resolvedValue || '<em>(empty)</em>'}</strong></div>`;
                } else {
                    html += `<div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-info professional-button solution-btn" data-solution-type="attribute" data-attribute="${attr.label}" data-value="${problem[attr.atlas] || ''}">Use ATLAS</button>
                        <button class="btn btn-outline-primary professional-button solution-btn" data-solution-type="attribute" data-attribute="${attr.label}" data-value="${problem[attr.osm] || ''}">Use OSM</button>
                    </div>`;
                }

                html += '</td></tr>';
            });

            html += '</tbody></table>';
        } else {
            html += '<div class="alert alert-success"><i class="fas fa-check-circle"></i> No attribute mismatches detected.</div>';
        }

        // Add global actions
        html += '<h6 class="mt-4"><i class="fas fa-globe"></i> Overall Status</h6>';
        html += '<div class="d-flex flex-wrap gap-2">';
        html += `<button class="btn btn-danger professional-button solution-btn" data-solution-type="global" data-solution="Not a valid match">
                    <i class="fas fa-times-circle"></i> Not a valid match
                </button>`;
        html += `<button class="btn btn-secondary professional-button solution-btn" data-solution-type="global" data-solution="Skip / I do not know">
                    <i class="fas fa-forward"></i> Skip
                </button>`;
        html += '</div>';

        html += '</div>';
        return html;
    }

    /**
     * Generate action buttons for duplicates problems (grouped view)
     */
    function generateDuplicatesActionButtons(problem) {
        // problem is a group with members
        const isOsmGroup = problem.group_type === 'osm';
        let title = isOsmGroup
            ? `<i class="fas fa-clone"></i> OSM duplicates for UIC ${problem.uic_ref || '(none)'} · local_ref ${problem.osm_local_ref || '(none)'}`
            : `<i class="fas fa-clone"></i> ATLAS duplicates for UIC ${problem.uic_ref || '(none)'} · designation ${problem.atlas_designation || '(none)'}`;

        let html = '<div class="problem-section-item">';
        html += `<h6>${title}</h6>`;
        html += '<div class="alert alert-info"><small><i class="fas fa-info-circle"></i> ' +
            (isOsmGroup ? 'Multiple OSM nodes share the same UIC and local_ref. Review each and decide which should remain.'
                : 'Multiple ATLAS entries share the UIC number and designation. Review and decide which should remain.') +
            '</small></div>';

        // Table of members
        html += '<table class="table table-sm"><thead><tr>' +
            '<th>Source</th><th>Identifier</th><th>Name</th><th>Coords</th><th>Action</th></tr></thead><tbody>';

        (problem.members || []).forEach(member => {
            const { badge, ident, name, isOsm } = getMemberDisplayInfo(member, problem.group_type);
            const coords = isOsm
                ? (member.osm_lat && member.osm_lon ? `${Math.round(member.osm_lat * 1e5) / 1e5}, ${Math.round(member.osm_lon * 1e5) / 1e5}` : '-')
                : (member.atlas_lat && member.atlas_lon ? `${Math.round(member.atlas_lat * 1e5) / 1e5}, ${Math.round(member.atlas_lon * 1e5) / 1e5}` : '-');

            const hasSolution = typeof member.solution === 'string' && member.solution.trim() !== '';
            const isKeep = hasSolution && member.solution.trim().toLowerCase() === 'keep';
            const isDelete = hasSolution && member.solution.trim().toLowerCase().indexOf('delete') !== -1;
            const keepBtnClass = isKeep ? 'btn-success' : 'btn-outline-success';
            const deleteBtnClass = isDelete ? 'btn-danger' : 'btn-outline-danger';

            html += `<tr>
                <td>${badge}</td>
                <td>${ident}</td>
                <td>${name || '-'}</td>
                <td>${coords}</td>
                <td>
                    <div class="d-flex flex-wrap gap-2">
                        <button class="btn ${keepBtnClass} btn-sm professional-button solution-btn" data-solution="Keep" data-problem="duplicates" data-target-stop-id="${member.stop_id}">
                            <i class="fas fa-check-circle"></i> Keep
                        </button>
                        <button class="btn ${deleteBtnClass} btn-sm professional-button solution-btn" data-solution="Should be deleted" data-problem="duplicates" data-target-stop-id="${member.stop_id}">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </td>
            </tr>`;
        });

        html += '</tbody></table>';

        // Global actions for duplicates
        html += '<h6 class="mt-4"><i class="fas fa-globe"></i> Overall Status</h6>';
        html += '<div class="d-flex flex-wrap gap-2">';
        html += `<button class="btn btn-secondary professional-button solution-btn" data-solution-type="global" data-solution="Skip / I do not know">
                    <i class="fas fa-forward"></i> Skip
                </button>`;
        html += '</div>';

        html += '</div>';
        return html;
    }

    /**
     * Generate solution status section for duplicates problems
     */
    function generateDuplicatesSolutionStatusSection(problem) {
        const solvedMembers = (problem.members || []).filter(m => typeof m.solution === 'string' && m.solution.trim() !== '');
        if (solvedMembers.length === 0) {
            return '';
        }

        const hasPersistentSolutions = solvedMembers.some(m => m.is_persistent);
        let persistenceHtml = '';

        if (hasPersistentSolutions) {
            persistenceHtml = `
                <div class="mt-2">
                    <span class="badge badge-success"><i class="fas fa-database"></i> Some solutions are persistent</span>
                    <small class="text-muted ml-2">Persistent solutions will be automatically applied after data imports</small>
                </div>
            `;
        } else {
            persistenceHtml = `
                <div class="mt-2">
                    <button class="btn btn-sm btn-outline-success make-persistent-duplicates-btn" 
                            data-problem-id="${problem.id}" 
                            data-problem-type="${problem.problem}">
                        <i class="fas fa-thumbtack"></i> Make All Persistent
                    </button>
                    <small class="text-muted ml-2">Save all current solutions for future data imports</small>
                </div>
            `;
        }

        return `
            <div class="problem-section-item solution-status-section">
                <h6><i class="fas fa-check-circle text-success"></i> Current Solution</h6>
                <div class="alert alert-success solution-display">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>Proposed Solution:</strong>
                            <ul class="mb-0 mt-2">
                                ${solvedMembers.map(m => {
            const isOsm = problem.group_type === 'osm' ? true : (problem.group_type === 'atlas' ? false : !!m.osm_node_id);
            const sourceBadge = isOsm ? '<span class="badge badge-secondary">OSM</span>' : '<span class="badge badge-secondary">ATLAS</span>';
            const ident = isOsm ? (m.osm_node_id || '-') : (m.sloid || '-');
            const sol = (m.solution || '').trim();
            const persistentIcon = m.is_persistent ? ' <i class="fas fa-database"></i>' : '';
            return `<li>${sourceBadge} ${ident} → <strong>${sol}</strong>${persistentIcon}</li>`;
        }).join('')}
                            </ul>
                            <small class="text-muted">You can modify any member's decision using the buttons below.</small>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary clear-duplicates-solutions-btn" 
                                data-problem-id="${problem.id}" 
                                data-problem-type="${problem.problem}">
                            <i class="fas fa-undo"></i> Clear All
                        </button>
                    </div>
                    ${persistenceHtml}
                </div>
            </div>
        `;
    }

    /**
     * Generate notes section for duplicates problems
     */
    function generateDuplicatesNotesSection(problem) {
        let html = '<div class="problem-section-item">';
        html += '<h6><i class="fas fa-sticky-note"></i> Notes</h6>';
        html += '<p><small class="text-muted">Add notes for individual duplicate entries below.</small></p>';

        (problem.members || []).forEach(member => {
            const { badge, ident, name, isOsm } = getMemberDisplayInfo(member, problem.group_type);

            html += `
                <div class="mb-3">
                    <label class="form-label">${badge} ${ident} - ${name}</label>
                    <div class="note-editor">
                        <textarea class="form-control member-note-text" 
                                placeholder="Add a note for this ${isOsm ? 'OSM' : 'ATLAS'} entry..."
                                data-stop-id="${member.stop_id}"
                                data-note-type="${isOsm ? 'osm' : 'atlas'}"
                                data-sloid="${isOsm ? '' : (member.sloid || '')}"
                                data-osm-node-id="${isOsm ? (member.osm_node_id || '') : ''}">${isOsm ? (member.osm_note || '') : (member.atlas_note || '')}</textarea>
                        <div class="form-check mt-1">
                            <input class="form-check-input member-note-persist" type="checkbox" 
                                   data-stop-id="${member.stop_id}"
                                   ${isOsm ? (member.osm_note_is_persistent ? 'checked' : '') : (member.atlas_note_is_persistent ? 'checked' : '')}>
                            <label class="form-check-label">Make note persistent across imports</label>
                        </div>
                        <button class="btn btn-info btn-sm professional-button save-member-note mt-2" 
                                data-note-type="${isOsm ? 'osm' : 'atlas'}" 
                                data-sloid="${isOsm ? '' : (member.sloid || '')}" 
                                data-osm-node-id="${isOsm ? (member.osm_node_id || '') : ''}" 
                                data-stop-id="${member.stop_id}">
                            Save Note
                        </button>
                    </div>
                </div>`;
        });

        html += '</div>';
        return html;
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
                const isAtlas = problem.stop_type === 'unmatched';
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

    /**
     * Render the UI for a single problem. Returns HTML string.
     */
    function renderSingleProblemUI(problem, entryIndex, issueIndex, totalIssues) {
        const problemType = problem.problem ? problem.problem.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : "Unknown";
        const safeId = String(problem.id).replace(/[^a-zA-Z0-9_-]/g, '-');
        let html = `<div class="issue-container" id="issue-${safeId}" data-problem-id="${problem.id}" data-stop-id="${problem.stop_id}">`;

        // Header for the issue
        // Add priority circle if present - match filter design
        let priorityBadge = '';
        if (problem.priority && !isNaN(problem.priority)) {
            const pr = String(problem.priority);
            const prClass = pr === '1' ? 'pr-1' : pr === '2' ? 'pr-2' : pr === '3' ? 'pr-3' : '';
            const selectedClass = '';
            priorityBadge = ` <span class="priority-circle ${prClass} ${selectedClass}"><span class="pc-text">P${pr}</span></span>`;
        }
        let displayText = `${problemType}${priorityBadge}`;
        if (totalIssues > 1) {
            displayText += ` (Issue ${issueIndex + 1}/${totalIssues})`;
        }

        // Add distance indicator for distance problems
        if (problem.problem === 'distance' && problem.distance_m) {
            const distance = Math.round(problem.distance_m);
            const distanceClass = distance > 100 ? 'high-distance' : '';
            displayText += `<span class="distance-indicator ${distanceClass}">(${distance}m apart)</span>`;
        }

        // Add persistence indicator to header if solution is persistent
        let persistenceIcon = '';
        if (problem.is_persistent) {
            persistenceIcon = ` <i class="fas fa-database text-success" title="This solution is persistent"></i>`;
        }

        html += `<h5 class="text-center mb-3">${displayText}${persistenceIcon}</h5>`;

        // Generate action buttons and content based on problem type
        let actionButtonsHtml = '';

        // Handle duplicates differently due to their multi-member structure
        if (problem.problem === 'duplicates') {
            if (Array.isArray(problem.members) && problem.members.length > 0) {
                // Current Solution for duplicates
                actionButtonsHtml += generateDuplicatesSolutionStatusSection(problem);
                // Resolution Actions for duplicates
                actionButtonsHtml += generateDuplicatesActionButtons(problem);
            } else {
                // Fallback for non-group duplicates (no members available)
                actionButtonsHtml += wrapInSection(
                    '<i class="fas fa-clone"></i> Duplicates',
                    '<div class="alert alert-info"><small>This entry is part of a duplicates group. Open the Duplicates view to resolve this issue.</small></div>' +
                    '<button class="btn btn-sm btn-outline-primary professional-button" onclick="ProblemsData.updateProblemTypeFilter(\'duplicates\', \'all\')">' +
                    '<i class="fas fa-external-link-alt"></i> Open Duplicates'
                    + '</button>'
                );
            }
        } else {
            // Current Solution for other problem types
            const clearButtonDataAttrs = {
                'data-problem-id': problem.id,
                'data-problem-type': problem.problem,
                'data-stop-id': problem.stop_id
            };
            actionButtonsHtml += generateSolutionStatusSection(problem, clearButtonDataAttrs);

            // Resolution Actions for other problem types
            switch (problem.problem) {
                case 'distance':
                    actionButtonsHtml += generateDistanceActionButtons(problem);
                    break;
                case 'unmatched':
                    actionButtonsHtml += generateIsolatedActionButtons(problem);
                    break;
                case 'attributes':
                    actionButtonsHtml += generateAttributeComparisonHtml(problem);
                    actionButtonsHtml += generateAttributesActionButtons(problem);
                    break;
            }
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
            root: document.getElementById('problemContent'),
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

                        // Update notes based on problem type
                        if (problem.problem === 'duplicates' && Array.isArray(problem.members) && problem.members.length > 0) {
                            // Show duplicates notes container and populate it
                            $('#notesSection').show();
                            $('#standardNotesContainer').hide();
                            $('#duplicatesNotesContainer').show().html(generateDuplicatesNotesSection(problem));
                        } else {
                            // Show standard notes container for other problem types
                            $('#notesSection').show();
                            $('#standardNotesContainer').show();
                            $('#duplicatesNotesContainer').hide();
                            if (window.ProblemsNotes && window.ProblemsNotes.loadNotesForProblem) {
                                window.ProblemsNotes.loadNotesForProblem(problem);
                            }
                        }
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
            $('#problemTypeDisplay').text(`Group ${index + 1} of ${totalProblems}`);
        } else {
            $('#problemTypeDisplay').text(`Entry ${index + 1} of ${totalProblems} (${problemCount} ${problemText})`);
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

            // Load notes for the first problem and setup notes container visibility
            if (firstProblem.problem === 'duplicates' && Array.isArray(firstProblem.members) && firstProblem.members.length > 0) {
                // Show duplicates notes container and populate it
                $('#notesSection').show();
                $('#standardNotesContainer').hide();
                $('#duplicatesNotesContainer').show().html(generateDuplicatesNotesSection(firstProblem));
            } else {
                // Show standard notes container for other problem types
                $('#notesSection').show();
                $('#standardNotesContainer').show();
                $('#duplicatesNotesContainer').hide();
                if (window.ProblemsNotes && window.ProblemsNotes.loadNotesForProblem) {
                    window.ProblemsNotes.loadNotesForProblem(firstProblem);
                }
            }
        }

        // Add scroll indicator if needed
        const problemContent = $('#problemContent');
        let scrollIndicator = problemContent.find('.scroll-indicator');
        if (currentEntryProblems.length > 1) {
            if (scrollIndicator.length === 0) {
                scrollIndicator = $('<div class="scroll-indicator"><i class="fas fa-chevron-down"></i></div>');
                problemContent.append(scrollIndicator);
            }
            setTimeout(() => scrollIndicator.addClass('visible'), 100);

            // Hide indicator on scroll
            problemContent.off('scroll.indicator').on('scroll.indicator', () => {
                scrollIndicator.removeClass('visible');
            });

        } else {
            scrollIndicator.remove();
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
        generateSolutionStatusSection,
        generateAttributeComparisonHtml,
        getMismatchedAttributes,
        generateDistanceActionButtons,
        generateIsolatedActionButtons,
        generateAttributesActionButtons,
        generateDuplicatesActionButtons,
        generateDuplicatesSolutionStatusSection,
        generateDuplicatesNotesSection,
        renderSingleProblemUI,
        setupIntersectionObserver,
        displayProblem,
        updateNavButtons,
        showTemporaryMessage
    };
})();
