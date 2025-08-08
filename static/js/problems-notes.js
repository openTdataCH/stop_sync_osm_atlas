// problems-notes.js - Notes management for the Problem Identification Page

/**
 * ProblemsNotes - Note loading, saving, and persistence functionality
 * Depends on: ProblemsState, ProblemsUI
 */
window.ProblemsNotes = (function() {
    'use strict';

    /**
     * Load and display notes for current problem
     */
    function loadNotesForProblem(problem) {
        ProblemsState.setCurrentProblem(problem);
        
        // Show notes section
        $('#notesSection').show();
        
        // Load ATLAS note
        if (problem.sloid) {
            $('#atlasNote').val(problem.atlas_note || '');
            $('#atlasNoteContainer').show();
            
            // Check if ATLAS note is persistent (using the new flag)
            const isAtlasNotePersistent = problem.atlas_note_is_persistent || false;
            const atlasCheckbox = $('#atlasNotePersistentCheckbox');

            if (atlasCheckbox.length === 0) {
                const persistentHtml = `
                    <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" id="atlasNotePersistentCheckbox" ${isAtlasNotePersistent ? 'checked' : ''}>
                        <label class="form-check-label" for="atlasNotePersistentCheckbox">
                            Make note persistent across imports
                            ${isAtlasNotePersistent ? '<span class="badge badge-success ml-2">Persistent</span>' : ''}
                        </label>
                    </div>
                `;
                $('#atlasNoteContainer .input-group').after(persistentHtml);
            } else {
                atlasCheckbox.prop('checked', isAtlasNotePersistent);
                const label = atlasCheckbox.siblings('label');
                label.find('.badge').remove();
                if (isAtlasNotePersistent) {
                    label.append('<span class="badge badge-success ml-2">Persistent</span>');
                }
            }
        } else {
            $('#atlasNoteContainer').hide();
        }
        
        // Load OSM note and editor link
        if (problem.osm_node_id) {
            $('#osmNote').val(problem.osm_note || '');
            $('#osmNoteContainer').show();
            
            // Check if OSM note is persistent (using the new flag)
            const isOsmNotePersistent = problem.osm_note_is_persistent || false;
            const osmCheckbox = $('#osmNotePersistentCheckbox');
            
            if (osmCheckbox.length === 0) {
                const persistentHtml = `
                    <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" id="osmNotePersistentCheckbox" ${isOsmNotePersistent ? 'checked' : ''}>
                        <label class="form-check-label" for="osmNotePersistentCheckbox">
                            Make note persistent across imports
                            ${isOsmNotePersistent ? '<span class="badge badge-success ml-2">Persistent</span>' : ''}
                        </label>
                    </div>
                `;
                $('#osmNoteContainer .input-group').after(persistentHtml);
            } else {
                osmCheckbox.prop('checked', isOsmNotePersistent);
                const label = osmCheckbox.siblings('label');
                label.find('.badge').remove();
                if (isOsmNotePersistent) {
                    label.append('<span class="badge badge-success ml-2">Persistent</span>');
                }
            }
            
            // Set up OSM iD editor link
            const osmEditorUrl = `https://www.openstreetmap.org/edit?node=${problem.osm_node_id}`;
            $('#osmEditorLink').attr('href', osmEditorUrl);
            $('#osmEditorLinkContainer').show();
        } else {
            $('#osmNoteContainer').hide();
            $('#osmEditorLinkContainer').hide();
        }
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
            problem_id: currentProblem.stop_id, // Use stop_id for backend context
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
                    // Update the checkbox and badge if needed
                    const persistentCheckbox = $(`#${noteType}NotePersistentCheckbox`);
                    const badge = persistentCheckbox.siblings('label').find('.badge');
                    
                    if (response.is_persistent) {
                        if (badge.length === 0) {
                            persistentCheckbox.siblings('label').append('<span class="badge badge-success ml-2">Persistent</span>');
                        }
                        persistentCheckbox.prop('checked', true);
                    } else {
                        badge.remove();
                        persistentCheckbox.prop('checked', false);
                    }
                    
                    // Update the current problem object with the new note and its persistent status
                    if (noteType === 'atlas') {
                        currentProblem.atlas_note = noteContent;
                        currentProblem.atlas_note_is_persistent = response.is_persistent;
                    } else {
                        currentProblem.osm_note = noteContent;
                        currentProblem.osm_note_is_persistent = response.is_persistent;
                    }
                    
                    // Provide clear feedback about persistence status
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
