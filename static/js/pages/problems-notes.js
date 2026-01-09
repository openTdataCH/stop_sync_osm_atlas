// problems-notes.js - Notes management for the Problem Identification Page

/**
 * ProblemsNotes - Note loading, saving, and persistence functionality
 * Depends on: ProblemsState, ProblemsUI
 */
window.ProblemsNotes = (function () {
    'use strict';

    SharedUtils.setupCSRFToken();

    /**
     * Render "other users' notes" into a container
     */
    function renderOthersNotes(container, others) {
        const list = $(container);
        if (!list.length) return;

        if (!others || others.length === 0) {
            list.html('<div class="small text-muted">Other user notes</div><div class="text-muted small"><em>No other persistent notes.</em></div>');
            return;
        }
        const html = '<div class="small text-muted">Other user notes</div>' + others.map(o => {
            const ts = o.updated_at ? new Date(o.updated_at).toLocaleString() : '';
            return `<div class="card card-body py-2 px-3 mb-2">
                <div class="small"><strong>${o.author_email || 'Unknown user'}</strong> · <span class="text-muted">${ts}</span></div>
                <div>${SharedUtils.escapeHtml(o.note || '')}</div>
            </div>`;
        }).join('');
        list.html(html);
    }

    /**
     * Save a note via API (shared by standard and duplicate notes)
     */
    function saveNoteToApi(noteType, entityId, noteContent, isPersistent, btn, callback) {
        const data = { note: noteContent, make_persistent: isPersistent };
        if (noteType === 'atlas') data.sloid = entityId;
        else data.osm_node_id = entityId;

        const originalText = btn.text();
        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Saving...');

        $.ajax({
            url: `/api/save_note/${noteType}`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(data),
            success: function (response) {
                btn.prop('disabled', false).text(originalText);
                if (response.success) {
                    const status = response.is_persistent ? 'as persistent data' : 'temporarily';
                    const icon = response.is_persistent ? 'database' : 'clock';
                    window.ProblemsUI?.showTemporaryMessage?.(`Note saved ${status}! <i class="fas fa-${icon}"></i>`, 'success');
                    callback?.(response);
                } else {
                    window.ProblemsUI?.showTemporaryMessage?.(`Error: ${response.error}`, 'error');
                }
            },
            error: function (xhr, status, error) {
                btn.prop('disabled', false).text(originalText);
                window.ProblemsUI?.showTemporaryMessage?.(`Error: ${error}`, 'error');
            }
        });
    }

    /**
     * Load and display notes for a standard problem (distance, unmatched, attributes)
     */
    function loadNotesForProblem(problem) {
        ProblemsState.setCurrentProblem(problem);
        $('#notesSection').show();

        // ATLAS note
        if (problem.sloid) {
            const label = `<span class="badge badge-secondary">ATLAS</span> ${problem.sloid} - ${problem.atlas_designation_official || problem.atlas_designation || '-'}`;
            $('#atlasNoteContainer .form-label').html(label);
            $.getJSON('/api/notes', { sloid: problem.sloid }, resp => {
                const your = resp?.your;
                $('#atlasNote').val(your?.note || '');
                ensurePersistentCheckbox('atlas', !!your?.is_persistent);
                renderOthersNotes('#atlasNoteContainer .others-notes', resp?.others || []);
            }).fail(() => {
                $('#atlasNote').val('');
                ensurePersistentCheckbox('atlas', false);
                renderOthersNotes('#atlasNoteContainer .others-notes', []);
            });
            $('#atlasNoteContainer').show();
        } else {
            $('#atlasNoteContainer').hide();
        }

        // OSM note
        if (problem.osm_node_id) {
            const label = `<span class="badge badge-secondary">OSM</span> ${problem.osm_node_id} - ${problem.osm_name || problem.osm_uic_name || '-'}`;
            $('#osmNoteContainer .form-label').html(label);
            $.getJSON('/api/notes', { osm_node_id: problem.osm_node_id }, resp => {
                const your = resp?.your;
                $('#osmNote').val(your?.note || '');
                ensurePersistentCheckbox('osm', !!your?.is_persistent);
                renderOthersNotes('#osmNoteContainer .others-notes', resp?.others || []);
            }).fail(() => {
                $('#osmNote').val('');
                ensurePersistentCheckbox('osm', false);
                renderOthersNotes('#osmNoteContainer .others-notes', []);
            });
            $('#osmNoteContainer').show();
        } else {
            $('#osmNoteContainer').hide();
        }
    }

    function ensurePersistentCheckbox(type, checked) {
        const id = type === 'atlas' ? 'atlasNotePersistentCheckbox' : 'osmNotePersistentCheckbox';
        const container = type === 'atlas' ? '#atlasNoteContainer .note-editor' : '#osmNoteContainer .note-editor';
        let checkbox = $('#' + id);
        if (!checkbox.length) {
            const html = `<label class="form-check form-check-inline align-middle ml-2 mb-0 small">
                <input class="form-check-input" type="checkbox" id="${id}" ${checked ? 'checked' : ''}>
                <span class="form-check-label"> Make persistent</span>
            </label>`;
            $(container).find('button[id^="save"]').first().after(html);
        } else {
            checkbox.prop('checked', !!checked);
        }
    }

    /**
     * Load notes for duplicates problem (renders note editor per member)
     */
    function loadNotesForDuplicates(problem) {
        ProblemsState.setCurrentProblem(problem);
        $('#notesSection').show();
        $('#standardNotesContainer').hide();

        const container = $('#duplicatesNotesContainer').empty().show();
        if (!problem.members?.length) {
            container.html('<div class="text-muted"><em>No members in this duplicate group.</em></div>');
            return;
        }

        const isOsm = problem.group_type === 'osm';
        let html = '<div class="problem-section-item"><h6><i class="fas fa-sticky-note"></i> Notes</h6>';

        problem.members.forEach((m, i) => {
            const id = `dup-${i}`;
            const entityId = isOsm ? m.osm_node_id : m.sloid;
            const name = isOsm ? (m.osm_name || '-') : (m.atlas_designation_official || m.atlas_designation || '-');
            const badge = isOsm ? 'OSM' : 'ATLAS';

            html += `<div class="mb-3" id="${id}-wrap" data-entity="${entityId}" data-type="${isOsm ? 'osm' : 'atlas'}">
                <label class="form-label"><span class="badge badge-secondary">${badge}</span> ${entityId} - ${name}</label>
                <div class="note-editor">
                    <textarea id="${id}-txt" class="form-control" placeholder="Add a note..."></textarea>
                    <button id="${id}-btn" class="btn btn-sm btn-info mt-2 professional-button">Save Note</button>
                    <label class="form-check form-check-inline align-middle ml-2 mb-0 small">
                        <input class="form-check-input" type="checkbox" id="${id}-chk"> <span class="form-check-label">Make persistent</span>
                    </label>
                </div>
                <div class="others-notes mt-2" id="${id}-others"></div>
            </div>`;
        });
        html += '</div>';
        container.html(html);

        // Fetch notes and attach handlers
        problem.members.forEach((m, i) => {
            const id = `dup-${i}`;
            const entityId = isOsm ? m.osm_node_id : m.sloid;
            const params = isOsm ? { osm_node_id: entityId } : { sloid: entityId };

            $.getJSON('/api/notes', params, resp => {
                $(`#${id}-txt`).val(resp?.your?.note || '');
                $(`#${id}-chk`).prop('checked', !!resp?.your?.is_persistent);
                renderOthersNotes(`#${id}-others`, resp?.others || []);
            }).fail(() => renderOthersNotes(`#${id}-others`, []));

            $(`#${id}-btn`).on('click', function () {
                const noteType = isOsm ? 'osm' : 'atlas';
                const content = $(`#${id}-txt`).val();
                const persist = $(`#${id}-chk`).is(':checked') || ProblemsState.getAutoPersistNotesEnabled();
                saveNoteToApi(noteType, entityId, content, persist, $(this));
            });
        });
    }

    /**
     * Save note from standard containers (called by external click handlers)
     */
    function saveNote(noteType, noteContent) {
        const problem = ProblemsState.getCurrentProblem();
        if (!problem) {
            window.ProblemsUI?.showTemporaryMessage?.('No problem selected', 'error');
            return;
        }

        const entityId = noteType === 'atlas' ? problem.sloid : problem.osm_node_id;
        if (!entityId) {
            window.ProblemsUI?.showTemporaryMessage?.(`Cannot save ${noteType} note: missing ID`, 'error');
            return;
        }

        const checkbox = $(`#${noteType}NotePersistentCheckbox`);
        const isPersistent = checkbox.is(':checked') || ProblemsState.getAutoPersistNotesEnabled();
        if (isPersistent) checkbox.prop('checked', true);

        const btn = $(`#save${noteType.charAt(0).toUpperCase() + noteType.slice(1)}Note`);
        saveNoteToApi(noteType, entityId, noteContent, isPersistent, btn, resp => {
            ensurePersistentCheckbox(noteType, !!resp.is_persistent);
        });
    }

    return { loadNotesForProblem, loadNotesForDuplicates, saveNote };
})();
