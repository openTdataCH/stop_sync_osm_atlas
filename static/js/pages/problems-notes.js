// problems-notes.js - Notes management for the Problem Identification Page

/**
 * ProblemsNotes - Note loading, saving, and persistence functionality
 * Depends on: ProblemsState, ProblemsUI
 */
window.ProblemsNotes = (function() {
    'use strict';

    // Setup CSRF token for AJAX requests
    SharedUtils.setupCSRFToken();

    /**
     * Load and display notes for current problem
     */
    function loadNotesForProblem(problem) {
        ProblemsState.setCurrentProblem(problem);
        
        // Show notes section
        $('#notesSection').show();
        
        // Load ATLAS note with duplicates-style label (badge + ID + name)
        if (problem.sloid) {
            const atlasName = problem.atlas_designation_official || problem.atlas_designation || '-';
            const atlasLabel = `<span class="badge badge-secondary">ATLAS</span> ${problem.sloid} - ${atlasName}`;
            $('#atlasNoteContainer .form-label').html(atlasLabel);
            // Fetch your and others' notes for ATLAS
            $.getJSON('/api/notes', { sloid: problem.sloid }, function(resp){
                const your = resp && resp.your ? resp.your : null;
                const others = resp && Array.isArray(resp.others) ? resp.others : [];
                $('#atlasNote').val(your && your.note ? your.note : '');
                renderOthersNotes('atlas', others);
                const isPersistent = !!(your && your.is_persistent);
                ensurePersistentCheckbox('atlas', isPersistent);
            }).fail(function(){
                $('#atlasNote').val('');
                renderOthersNotes('atlas', []);
                ensurePersistentCheckbox('atlas', false);
            });
            $('#atlasNoteContainer').show();
        } else {
            $('#atlasNoteContainer').hide();
        }
        
        // Load OSM note with duplicates-style label (badge + ID + name)
        if (problem.osm_node_id) {
            const osmName = problem.osm_name || problem.osm_uic_name || '-';
            const osmLabel = `<span class="badge badge-secondary">OSM</span> ${problem.osm_node_id} - ${osmName}`;
            $('#osmNoteContainer .form-label').html(osmLabel);
            // Fetch your and others' notes for OSM
            $.getJSON('/api/notes', { osm_node_id: problem.osm_node_id }, function(resp){
                const your = resp && resp.your ? resp.your : null;
                const others = resp && Array.isArray(resp.others) ? resp.others : [];
                $('#osmNote').val(your && your.note ? your.note : '');
                renderOthersNotes('osm', others);
                const isPersistent = !!(your && your.is_persistent);
                ensurePersistentCheckbox('osm', isPersistent);
            }).fail(function(){
                $('#osmNote').val('');
                renderOthersNotes('osm', []);
                ensurePersistentCheckbox('osm', false);
            });
            $('#osmNoteContainer').show();
        } else {
            $('#osmNoteContainer').hide();
        }
    }

    function ensurePersistentCheckbox(type, checked) {
        const id = type === 'atlas' ? 'atlasNotePersistentCheckbox' : 'osmNotePersistentCheckbox';
        const container = type === 'atlas' ? '#atlasNoteContainer .note-editor' : '#osmNoteContainer .note-editor';
        const checkbox = $('#' + id);
        if (checkbox.length === 0) {
            const html = `
                <label class="form-check form-check-inline align-middle ml-2 mb-0 small">
                    <input class="form-check-input" type="checkbox" id="${id}" ${checked ? 'checked' : ''}>
                    <span class="form-check-label"> Make persistent</span>
                </label>
            `;
            // Place next to the Save button
            const saveBtn = $(container).find('button[id^="save"]').first();
            if (saveBtn.length) {
                saveBtn.after(html);
            } else {
                $(container).append(html);
            }
        } else {
            checkbox.prop('checked', !!checked);
        }
    }

    function renderOthersNotes(type, others) {
        const containerId = type === 'atlas' ? '#atlasNoteContainer' : '#osmNoteContainer';
        let list = $(containerId + ' .others-notes');
        if (list.length === 0) {
            list = $('<div class="others-notes mt-2"></div>');
            $(containerId + ' .note-editor').after(list);
        }
        if (!others || others.length === 0) {
            list.html('<div class="small text-muted">Other user notes</div><div class="text-muted small"><em>No other persistent notes.</em></div>');
            return;
        }
        const html = `<div class="small text-muted">Other user notes</div>` + others.map(o => {
            const ts = o.updated_at ? new Date(o.updated_at).toLocaleString() : '';
            return `<div class="card card-body py-2 px-3 mb-2">
                        <div class="small"><strong>${o.author_email || 'Unknown user'}</strong> · <span class="text-muted">${ts}</span></div>
                        <div>${SharedUtils.escapeHtml(o.note || '')}</div>
                    </div>`;
        }).join('');
        list.html(html);
    }

    /**
     * Save notes functionality
     */
    function saveNote(noteType, noteContent) {
        const currentProblem = ProblemsState.getCurrentProblem();
        
        if (!currentProblem) {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage('No problem selected', 'error');
            }
            return;
        }
        
        // Check if the persistent checkbox is checked or auto-persist is enabled
        const persistentCheckbox = $(`#${noteType}NotePersistentCheckbox`);
        const isCheckboxChecked = persistentCheckbox.length > 0 && persistentCheckbox.is(':checked');
        const autoPersistNotesEnabled = ProblemsState.getAutoPersistNotesEnabled();
        const isPersistent = isCheckboxChecked || autoPersistNotesEnabled;
        
        // If auto-persist is enabled but the checkbox doesn't reflect it, update the checkbox
        if (autoPersistNotesEnabled && persistentCheckbox.length > 0 && !persistentCheckbox.is(':checked')) {
            persistentCheckbox.prop('checked', true);
        }
        
        const data = {
            note: noteContent,
            make_persistent: isPersistent
        };
        
        if (noteType === 'atlas' && currentProblem.sloid) {
            data.sloid = currentProblem.sloid;
        } else if (noteType === 'osm' && currentProblem.osm_node_id) {
            data.osm_node_id = currentProblem.osm_node_id;
        } else {
            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                window.ProblemsUI.showTemporaryMessage(`Cannot save ${noteType} note: missing required ID`, 'error');
            }
            return;
        }
        
        // Show saving indicator
        const saveButton = $(`#save${noteType.charAt(0).toUpperCase() + noteType.slice(1)}Note`);
        const originalButtonText = saveButton.text();
        saveButton.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Saving...');
        
        $.ajax({
            url: `/api/save_note/${noteType}`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(data),
            success: function(response) {
                if (response.success) {
                    ensurePersistentCheckbox(noteType, !!response.is_persistent);
                    const persistenceStatus = response.is_persistent ? 'as persistent data' : 'temporarily (non-persistent)';
                    const statusIcon = response.is_persistent ? 'database' : 'clock';
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage(`${noteType.toUpperCase()} note saved ${persistenceStatus}! <i class="fas fa-${statusIcon}"></i>`, 'success');
                    }
                } else {
                    if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                        window.ProblemsUI.showTemporaryMessage(`Error saving ${noteType} note: ${response.error}`, 'error');
                    }
                }
                
                // Restore button
                saveButton.prop('disabled', false).text(originalButtonText);
            },
            error: function(xhr, status, error) {
                if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                    window.ProblemsUI.showTemporaryMessage(`Error saving ${noteType} note: ${error}`, 'error');
                }
                saveButton.prop('disabled', false).text(originalButtonText);
            }
        });
    }

    // Public API
    return {
        loadNotesForProblem,
        saveNote
    };
})();
