// manage-data.js - JavaScript for the Manage Data Page

$(document).ready(function() {
    // Setup CSRF token for AJAX requests
    SharedUtils.setupCSRFToken();

    // Use shared error message builder
    const buildErrorMessage = SharedUtils.buildErrorMessage;

    let currentPage = 1;
    let currentFilter = 'all';
    let currentTab = 'persistent'; // 'persistent' or 'non-persistent'
    let isAdmin = false;
    let currentUserEmail = null;
    
    // Initialize the manage data page with proper error handling
    function initializeManageDataPage() {
        try {
            // Setup event handlers first
            setupEventHandlers();
            
            // Load initial data for the default tab (persistent), but first detect admin
            if (window.__authStatusEndpoint) {
                $.getJSON(window.__authStatusEndpoint, function(status){
                    isAdmin = !!(status && status.is_admin);
                    currentUserEmail = (status && status.email) ? status.email : null;
                    if (!isAdmin) { $('#makeAllPersistentBtn').hide(); } else { $('#makeAllPersistentBtn').show(); }
                    loadPersistentData(currentPage, currentFilter);
                }).fail(function(){
                    $('#makeAllPersistentBtn').hide();
                    loadPersistentData(currentPage, currentFilter);
                });
            } else {
                loadPersistentData(currentPage, currentFilter);
            }
        } catch (error) {
            console.error('Error initializing manage data page:', error);
            showTemporaryMessage('Error initializing page. Please refresh.', 'error');
        }
    }
    
    // Setup all event handlers
    function setupEventHandlers() {
        // Tab switching with proper state management
        $('.nav-link[data-toggle="tab"]').on('shown.bs.tab', function(e) {
            const targetTab = $(e.target).attr('href').substring(1); // Remove #
            
            // Only proceed if we're actually switching tabs
            if (targetTab !== currentTab) {
                currentTab = targetTab;
                currentPage = 1; // Reset pagination when switching tabs
                
                // Clear pagination to avoid UI confusion
                $('#dataPagination').empty();
                
                // Load the appropriate data for the new tab
                if (currentTab === 'persistent') {
                    loadPersistentData(currentPage, currentFilter);
                } else if (currentTab === 'non-persistent') {
                    loadNonPersistentData(currentPage, currentFilter);
                }
            }
        });
        
        // Pagination click handler
        $(document).on('click', '.page-link', function(e) {
            e.preventDefault();
            const page = $(this).data('page');
            if (page && page !== currentPage) {
                currentPage = page;
                if (currentTab === 'persistent') {
                    loadPersistentData(currentPage, currentFilter);
                } else {
                    loadNonPersistentData(currentPage, currentFilter);
                }
            }
        });
        
        // Filter click handler
        $('.filter-type-btn').on('click', function(e) {
            e.preventDefault();
            const filter = $(this).data('type');
            if (filter !== currentFilter) {
                currentFilter = filter;
                currentPage = 1;
                if (currentTab === 'persistent') {
                    loadPersistentData(currentPage, currentFilter);
                } else {
                    loadNonPersistentData(currentPage, currentFilter);
                }
            }
        });
        
        // Delete button click handler
        $(document).on('click', '.delete-solution-btn', function() {
            const id = $(this).data('id');
            const type = $(this).data('type') || 'persistent';
            
            if (type === 'persistent') {
                // For persistent data, show the standard deletion modal
                $('#confirmDeleteBtn').data('id', id).data('type', type);
                $('#deleteConfirmModal').modal('show');
            } else {
                // For non-persistent data, show a different modal for clearing
                const dataType = $(this).data('data-type');
                const noteType = $(this).data('note-type');
                $('#confirmClearBtn').data('id', id)
                                     .data('data-type', dataType)
                                     .data('note-type', noteType);
                $('#clearConfirmModal').modal('show');
            }
        });
        
        // Confirm delete handler
        $('#confirmDeleteBtn').on('click', function() {
            const id = $(this).data('id');
            const type = $(this).data('type');
            
            if (type === 'persistent') {
                deletePersistentData(id);
            }
            $('#deleteConfirmModal').modal('hide');
        });

        // Confirm clear handler for non-persistent data
        $('#confirmClearBtn').on('click', function() {
            const id = $(this).data('id');
            const dataType = $(this).data('data-type');
            const noteType = $(this).data('note-type');
            clearNonPersistentData(id, dataType, noteType);
            $('#clearConfirmModal').modal('hide');
        });

        // Make persistent button handler
        $(document).on('click', '.make-persistent-btn', function() {
            const button = $(this);
            const id = button.data('id');
            const dataType = button.data('data-type'); // 'solution' or 'note'
            
            if (dataType === 'solution') {
                const stopId = button.closest('.solution-card').data('stop-id');
                const problemType = button.data('problem-type');
                // For solutions, the `id` we pass is the stop_id
                makePersistent(stopId, dataType, null, problemType);
            } else {
                const noteType = button.data('note-type');
                // For notes, the `id` is the identifier like 'atlas_...' or 'osm_...'
                makePersistent(id, dataType, noteType, null);
            }
        });

        // Make all persistent button handler
        $('#makeAllPersistentBtn').on('click', function() {
            makeAllPersistent();
        });

        // Make persistent item non-persistent (admin/owner)
        $(document).on('click', '.make-non-persistent-btn', function() {
            const id = $(this).data('id');
            const type = $(this).data('type'); // 'solution' or 'note'
            makeNonPersistent(id, type);
        });

        // Group notes: show add editor
        $(document).on('click', '.show-add-group-note', function(){
            const editor = $(this).closest('.my-note-editor');
            editor.find('.my-note-adder').show();
            $(this).hide();
        });

        // Group notes: cancel add
        $(document).on('click', '.cancel-add-group-note', function(){
            const editor = $(this).closest('.my-note-editor');
            editor.find('.my-note-adder').hide();
            editor.find('.show-add-group-note').show();
        });

        // Group notes: save/update your note
        $(document).on('click', '.save-group-note', function(){
            const btn = $(this);
            const card = btn.closest('.solution-card');
            const kind = btn.data('kind');
            const sloid = btn.data('sloid') || null;
            const osmNodeId = btn.data('osm-node-id') || null;
            const text = card.find('.my-note-text').val();
            const persist = card.find('.my-note-persist').is(':checked');
            const url = kind === 'atlas' ? '/api/save_note/atlas' : '/api/save_note/osm';
            const payload = kind === 'atlas' ? { sloid: sloid, note: text, make_persistent: persist } : { osm_node_id: osmNodeId, note: text, make_persistent: persist };
            const original = btn.html(); btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');
            $.ajax({ url: url, method: 'POST', contentType: 'application/json', data: JSON.stringify(payload) })
              .done(function(resp){ showTemporaryMessage('Note updated' + (resp && resp.is_persistent ? ' (persistent)' : ''), 'success'); })
              .fail(function(xhr){ showTemporaryMessage(buildErrorMessage(xhr, 'Error updating note', 'owner'), 'error'); })
              .always(function(){ btn.prop('disabled', false).html(original); });
        });

        // Group notes: add your first note
        $(document).on('click', '.add-group-note-save', function(){
            const btn = $(this);
            const card = btn.closest('.solution-card');
            const kind = btn.data('kind');
            const sloid = btn.data('sloid') || null;
            const osmNodeId = btn.data('osm-node-id') || null;
            const text = card.find('.my-note-text').val();
            const persist = card.find('.my-note-persist').is(':checked');
            const url = kind === 'atlas' ? '/api/save_note/atlas' : '/api/save_note/osm';
            const payload = kind === 'atlas' ? { sloid: sloid, note: text, make_persistent: persist } : { osm_node_id: osmNodeId, note: text, make_persistent: persist };
            const original = btn.html(); btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');
            $.ajax({ url: url, method: 'POST', contentType: 'application/json', data: JSON.stringify(payload) })
              .done(function(resp){ showTemporaryMessage('Note saved' + (resp && resp.is_persistent ? ' (persistent)' : ''), 'success'); loadPersistentData(currentPage, currentFilter); })
              .fail(function(xhr){ showTemporaryMessage(buildErrorMessage(xhr, 'Error saving note', 'owner'), 'error'); })
              .always(function(){ btn.prop('disabled', false).html(original); });
        });

        // Group notes: delete your note
        $(document).on('click', '.delete-group-note', function(){
            const id = $(this).data('note-id');
            if (!id) return;
            if (!confirm('Delete your note?')) return;
            $.ajax({ url: `/api/user_notes/${id}`, method: 'DELETE' })
              .done(function(resp){
                  showTemporaryMessage('Note deleted', 'success');
                  // In-place update: convert editor to "Add your note" state
                  const card = $(`.solution-card .delete-group-note[data-note-id="${id}"]`).closest('.solution-card');
                  const editor = card.find('.my-note-editor');
                  if (editor.length) {
                      editor.html(`
                          <button class="btn btn-sm btn-outline-primary show-add-group-note" ${card.hasClass('atlas_note') ? `data-kind="atlas" data-sloid="${card.find('[data-sloid]').data('sloid') || ''}"` : `data-kind="osm" data-osm-node-id="${card.find('[data-osm-node-id]').data('osm-node-id') || ''}"`}><i class="fas fa-plus"></i> Add your note</button>
                          <div class="my-note-adder mt-2" style="display:none;">
                              <textarea class="form-control form-control-sm my-note-text" rows="2" placeholder="Write a note..."></textarea>
                              <div class="d-flex align-items-center mt-1">
                                  <button class="btn btn-sm btn-primary mr-2 add-group-note-save" ${card.hasClass('atlas_note') ? `data-kind="atlas" data-sloid="${card.find('[data-sloid]').data('sloid') || ''}"` : `data-kind="osm" data-osm-node-id="${card.find('[data-osm-node-id]').data('osm-node-id') || ''}"`}><i class="fas fa-save"></i> Save</button>
                                  <label class="form-check form-check-inline mb-0 small">
                                      <input type="checkbox" class="form-check-input my-note-persist" checked> <span class="form-check-label"> Make persistent</span>
                                  </label>
                                  <button class="btn btn-sm btn-link text-muted ml-2 cancel-add-group-note">Cancel</button>
                              </div>
                          </div>
                      `);
                  } else {
                      // Fallback: reload group list
                      loadPersistentData(currentPage, currentFilter);
                  }
              })
              .fail(function(xhr){ showTemporaryMessage(buildErrorMessage(xhr, 'Error deleting note', 'owner'), 'error'); });
        });

        // Group notes: make your note non-persistent
        $(document).on('click', '.make-group-note-nonpersistent', function(){
            const id = $(this).data('note-id');
            if (!id) return;
            $.ajax({ url: `/api/user_notes/${id}/make_non_persistent`, method: 'POST', contentType: 'application/json', data: JSON.stringify({}) })
              .done(function(resp){
                  showTemporaryMessage('Note made non-persistent', 'success');
                  // Remove the editor from persistent group since your note is no longer persistent
                  const card = $(`.solution-card .make-group-note-nonpersistent[data-note-id="${id}"]`).closest('.solution-card');
                  const editor = card.find('.my-note-editor');
                  if (editor.length) {
                      editor.html(`
                          <button class="btn btn-sm btn-outline-primary show-add-group-note" ${card.hasClass('atlas_note') ? `data-kind="atlas" data-sloid="${card.find('[data-sloid]').data('sloid') || ''}"` : `data-kind="osm" data-osm-node-id="${card.find('[data-osm-node-id]').data('osm-node-id') || ''}"`}><i class="fas fa-plus"></i> Add your note</button>
                          <div class="my-note-adder mt-2" style="display:none;">
                              <textarea class="form-control form-control-sm my-note-text" rows="2" placeholder="Write a note..."></textarea>
                              <div class="d-flex align-items-center mt-1">
                                  <button class="btn btn-sm btn-primary mr-2 add-group-note-save" ${card.hasClass('atlas_note') ? `data-kind="atlas" data-sloid="${card.find('[data-sloid]').data('sloid') || ''}"` : `data-kind="osm" data-osm-node-id="${card.find('[data-osm-node-id]').data('osm-node-id') || ''}"`}><i class="fas fa-save"></i> Save</button>
                                  <label class="form-check form-check-inline mb-0 small">
                                      <input type="checkbox" class="form-check-input my-note-persist" checked> <span class="form-check-label"> Make persistent</span>
                                  </label>
                                  <button class="btn btn-sm btn-link text-muted ml-2 cancel-add-group-note">Cancel</button>
                              </div>
                          </div>
                      `);
                  } else {
                      // Fallback: reload group list
                      loadPersistentData(currentPage, currentFilter);
                  }
              })
              .fail(function(xhr){ showTemporaryMessage(buildErrorMessage(xhr, 'Error making non-persistent', 'owner'), 'error'); });
        });
    }
    
    // Load persistent data
    function loadPersistentData(page = 1, filter = 'all') {
        const container = $('#persistent-data-container');
        container.html(`
            <div class="text-center py-5">
                <div class="spinner-border" role="status">
                    <span class="sr-only">Loading...</span>
                </div>
                <p class="mt-2">Loading manage data...</p>
            </div>
        `);
        
        const params = { page: page, limit: 10 };
        if (filter !== 'all') {
            if (filter === 'atlas_note') {
                params.note_type = 'atlas';
            } else if (filter === 'osm_note') {
                params.note_type = 'osm';
            } else {
                params.problem_type = filter;
            }
        }
        
        $.getJSON('/api/persistent_data', params)
            .done(function(data) {
                let html = '';
                if (data.note_groups && data.note_groups.length > 0) {
                    html += renderNoteGroups(data.note_groups);
                }
                if (data.persistent_data && data.persistent_data.length > 0) {
                    data.persistent_data.forEach(item => {
                        html += renderPersistentDataItem(item);
                    });
                }
                if (!html) {
                    html = `
                        <div class="alert alert-warning">
                            <i class="fas fa-exclamation-triangle"></i> No persistent data found for the selected filter.
                        </div>
                    `;
                }
                container.html(html);
                
                generatePagination(data.page, Math.ceil(data.total / data.limit));
                updateClearAllButton('persistent', data.total);
            })
            .fail(function(xhr, status, error) {
                console.error('Error loading persistent data:', error);
                container.html(`
                    <div class="alert alert-danger">
                        <i class="fas fa-exclamation-circle"></i> Error loading persistent data: ${error}
                    </div>
                `);
                $('#dataPagination').empty();
            });
    }

    function renderNoteGroups(groups) {
        let html = '';
        groups.forEach(g => {
            const isAtlas = g.kind === 'atlas';
            const entityMeta = isAtlas ? `<div><strong>SLOID:</strong> ${g.sloid}</div>` : `<div><strong>OSM Node ID:</strong> ${g.osm_node_id}</div>`;
            const myEmail = currentUserEmail || null;
            const yourNote = (g.notes || []).find(n => n.author_email && myEmail && n.author_email === myEmail) || null;
            const otherNotes = (g.notes || []).filter(n => !yourNote || n.author_email !== yourNote.author_email);
            const othersHtml = otherNotes.map(n => {
                const ts = n.updated_at ? new Date(n.updated_at).toLocaleString() : '';
                return `<div class="card card-body py-2 px-3 mb-2">
                            <div class="small"><strong>${n.author_email || 'Unknown user'}</strong> · <span class="text-muted">${ts}</span></div>
                            <div>${SharedUtils.escapeHtml(n.note || '')}</div>
                        </div>`;
            }).join('');
            let yourEditor = '';
            if (myEmail) {
                if (yourNote) {
                    const ts = yourNote.updated_at ? new Date(yourNote.updated_at).toLocaleString() : '';
                    yourEditor = `
                        <div class="my-note-editor">
                            <label class="small text-muted mb-1">Your note ${ts ? `· <span class=\"text-muted\">${ts}</span>` : ''}</label>
                            <textarea class="form-control form-control-sm my-note-text" rows="2">${SharedUtils.escapeHtml(yourNote.note || '')}</textarea>
                            <div class="d-flex align-items-center mt-1">
                                <button class="btn btn-sm btn-primary mr-2 save-group-note" data-kind="${isAtlas ? 'atlas' : 'osm'}" ${isAtlas ? `data-sloid=\"${g.sloid}\"` : `data-osm-node-id=\"${g.osm_node_id}\"`} data-note-id="${yourNote.id}"><i class="fas fa-save"></i> Save</button>
                                <label class="form-check form-check-inline mb-0 small">
                                    <input type="checkbox" class="form-check-input my-note-persist" checked> <span class="form-check-label"> Make persistent</span>
                                </label>
                                <button class="btn btn-sm btn-warning ml-2 make-group-note-nonpersistent" data-note-id="${yourNote.id}"><i class="fas fa-undo"></i> Make Non-Persistent</button>
                                <button class="btn btn-sm btn-outline-danger ml-2 delete-group-note" data-note-id="${yourNote.id}"><i class="fas fa-trash"></i> Delete</button>
                            </div>
                        </div>`;
                } else {
                    yourEditor = `
                        <div class="my-note-editor">
                            <button class="btn btn-sm btn-outline-primary show-add-group-note" data-kind="${isAtlas ? 'atlas' : 'osm'}" ${isAtlas ? `data-sloid=\"${g.sloid}\"` : `data-osm-node-id=\"${g.osm_node_id}\"`}><i class="fas fa-plus"></i> Add your note</button>
                            <div class="my-note-adder mt-2" style="display:none;">
                                <textarea class="form-control form-control-sm my-note-text" rows="2" placeholder="Write a note..."></textarea>
                                <div class="d-flex align-items-center mt-1">
                                    <button class="btn btn-sm btn-primary mr-2 add-group-note-save" data-kind="${isAtlas ? 'atlas' : 'osm'}" ${isAtlas ? `data-sloid=\"${g.sloid}\"` : `data-osm-node-id=\"${g.osm_node_id}\"`}><i class="fas fa-save"></i> Save</button>
                                    <label class="form-check form-check-inline mb-0 small">
                                        <input type="checkbox" class="form-check-input my-note-persist" checked> <span class="form-check-label"> Make persistent</span>
                                    </label>
                                    <button class="btn btn-sm btn-link text-muted ml-2 cancel-add-group-note">Cancel</button>
                                </div>
                            </div>
                        </div>`;
                }
            }
            html += `
                <div class="card solution-card ${isAtlas ? 'atlas_note' : 'osm_note'}" data-item-type="persistent-group" ${isAtlas ? `data-sloid="${g.sloid}"` : `data-osm-node-id="${g.osm_node_id}"`}>
                    <div class="card-body">
                        <div class="solution-header">
                            <h5 class="card-title">
                                <span class="badge badge-${isAtlas ? 'info' : 'primary'}">${isAtlas ? 'ATLAS' : 'OSM'} Notes</span>
                                <small class="text-muted ml-2">Persistent</small>
                            </h5>
                        </div>
                        <div class="card-text">
                            ${entityMeta}
                            <div class="mt-2">
                                ${yourEditor}
                                <div class="small text-muted mt-2">Other user notes</div>
                                ${othersHtml || '<div class="text-muted small"><em>No other notes</em></div>'}
                            </div>
                        </div>
                    </div>
                </div>`;
        });
        return html;
    }
    
    // Load non-persistent data
    function loadNonPersistentData(page = 1, filter = 'all') {
        const container = $('#non-persistent-data-container');
        container.html(`
            <div class="text-center py-5">
                <div class="spinner-border" role="status">
                    <span class="sr-only">Loading...</span>
                </div>
                <p class="mt-2">Loading non-persistent data...</p>
            </div>
        `);
        
        const params = { page: page, limit: 10, filter: filter };
        
        $.getJSON('/api/non_persistent_data', params)
            .done(function(data) {
                if (!data.data || data.data.length === 0) {
                    container.html(`
                        <div class="alert alert-info">
                            <i class="fas fa-info-circle"></i> <strong>No non-persistent data found.</strong>
                            <br><small>This is good! Either all your work is already persistent, or you haven't saved any solutions/notes with auto-persist disabled.</small>
                            <br><small>To see items here: turn off auto-persist toggles in the Problems page, then save solutions or notes.</small>
                        </div>
                    `);
                    $('#dataPagination').empty();
                    return;
                }
                
                let html = '';
                data.data.forEach(item => {
                    html += renderNonPersistentDataItem(item);
                });
                container.html(html);
                
                generatePagination(data.page, Math.ceil(data.total / data.limit));
                updateClearAllButton('non-persistent', data.total);
            })
            .fail(function(xhr, status, error) {
                console.error('Error loading non-persistent data:', error);
                container.html(`
                    <div class="alert alert-danger">
                        <i class="fas fa-exclamation-circle"></i> Error loading non-persistent data: ${error}
                    </div>
                `);
                $('#dataPagination').empty();
            });
    }
    
    function renderPersistentDataItem(item) {
        if (!item || !item.id) { return ''; }
        const isNote = item.note_type === 'atlas' || item.note_type === 'osm';
        let cardClass, badgeClass, titleText;
        if (isNote) {
            if (item.note_type === 'atlas') { cardClass = 'atlas_note'; badgeClass = 'info'; titleText = 'ATLAS Note'; }
            else if (item.note_type === 'osm') { cardClass = 'osm_note'; badgeClass = 'primary'; titleText = 'OSM Note'; }
            else { cardClass = 'unknown_note'; badgeClass = 'secondary'; titleText = 'Unknown Note'; }
        } else {
            cardClass = item.problem_type || 'unknown';
            badgeClass = item.problem_type === 'distance' ? 'danger' : item.problem_type === 'isolated' ? 'warning' : item.problem_type === 'attributes' ? 'info' : 'secondary';
            titleText = (item.problem_type || 'Unknown').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        }
        const formattedDate = item.updated_at ? new Date(item.updated_at).toLocaleString() : 'Unknown';
        const content = isNote ? (item.note || '') : (item.solution || '');
        const authorLine = (item.author_email && item.author_email.trim().length > 0) ? `<div><strong>Author:</strong> ${item.author_email}</div>` : `<div><strong>Author:</strong> <em>Not a user</em></div>`;
        const canManage = isAdmin || (!!currentUserEmail && !!item.author_email && item.author_email === currentUserEmail);
        const actionButtons = canManage ? `
                        <div class="btn-group">
                             <button class="btn btn-sm btn-warning make-non-persistent-btn" data-id="${item.id}" data-type="${isNote ? 'note' : 'solution'}"><i class="fas fa-undo"></i> Make Non-Persistent</button>
                            <button class="btn btn-sm btn-outline-danger delete-solution-btn" data-id="${item.id}" data-type="persistent"><i class="fas fa-trash"></i> Clear</button>
                        </div>` : '';
        return `
            <div class="card solution-card ${cardClass}" data-id="${item.id}" data-item-type="persistent">
                <div class="card-body">
                    <div class="solution-header">
                        <h5 class="card-title">
                            <span class="badge badge-${badgeClass}">${titleText}</span>
                            <small class="text-muted ml-2">Persistent</small>
                        </h5>
                        ${actionButtons}
                    </div>
                    <div class="card-text">
                        <div><strong>SLOID:</strong> ${item.sloid || '<em>None</em>'}</div>
                        <div><strong>OSM Node ID:</strong> ${item.osm_node_id || '<em>None</em>'}</div>
                        ${authorLine}
                        <div><strong>Last Updated:</strong> ${formattedDate}</div>
                        <div class="solution-content"><strong>${isNote ? 'Note:' : 'Solution:'}</strong> ${content || '<em>Empty</em>'}</div>
                    </div>
                </div>
            </div>`;
    }

    function renderNonPersistentDataItem(item) {
        if (!item || !item.id) { return ''; }
        const isNote = item.type === 'note';
        let cardClass, badgeClass, titleText;
        if (isNote) {
            if (item.note_type === 'atlas') { cardClass = 'atlas_note'; badgeClass = 'info'; titleText = 'ATLAS Note'; }
            else if (item.note_type === 'osm') { cardClass = 'osm_note'; badgeClass = 'primary'; titleText = 'OSM Note'; }
            else { cardClass = 'unknown_note'; badgeClass = 'secondary'; titleText = 'Unknown Note'; }
        } else {
            cardClass = item.problem_type || 'unknown';
            badgeClass = item.problem_type === 'distance' ? 'danger' : item.problem_type === 'isolated' ? 'warning' : item.problem_type === 'attributes' ? 'info' : 'secondary';
            titleText = (item.problem_type || 'Unknown').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        }
        const content = isNote ? (item.note || '') : (item.solution || '');
        return `
            <div class="card solution-card ${cardClass}" data-id="${item.id}" data-item-type="non-persistent" ${!isNote ? `data-stop-id="${item.stop_id}"` : ''} ${isNote && item.sloid ? `data-sloid="${item.sloid}"` : ''} ${isNote && item.osm_node_id ? `data-osm-node-id="${item.osm_node_id}"` : ''}>
                <div class="card-body">
                    <div class="solution-header">
                        <h5 class="card-title">
                            <span class="badge badge-${badgeClass}">${titleText}</span>
                            <small class="text-muted ml-2">Temporary</small>
                        </h5>
                        <div class="btn-group">
                            <button class="btn btn-sm btn-outline-success make-persistent-btn" data-id="${item.id}" data-data-type="${isNote ? 'note' : 'solution'}" ${isNote ? `data-note-type="${item.note_type}"` : ''} ${isNote && item.sloid ? `data-sloid="${item.sloid}"` : ''} ${isNote && item.osm_node_id ? `data-osm-node-id="${item.osm_node_id}"` : ''} ${!isNote ? `data-problem-type="${item.problem_type}"` : ''}>
                                <i class="fas fa-thumbtack"></i> Make Persistent
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-solution-btn" data-id="${item.id}" data-type="non-persistent" data-data-type="${isNote ? 'note' : 'solution'}" ${isNote ? `data-note-type="${item.note_type}"` : ''}>
                                <i class="fas fa-trash"></i> Clear
                            </button>
                        </div>
                    </div>
                    <div class="card-text">
                        <div><strong>SLOID:</strong> ${item.sloid || '<em>None</em>'}</div>
                        <div><strong>OSM Node ID:</strong> ${item.osm_node_id || '<em>None</em>'}</div>
                        <div class="solution-content"><strong>${isNote ? 'Note:' : 'Solution:'}</strong> ${content || '<em>Empty</em>'}</div>
                    </div>
                </div>
            </div>`;
    }
    
    function generatePagination(currentPage, totalPages) {
        if (totalPages <= 1) { $('#dataPagination').empty(); return; }
        let html = `
            <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage - 1}" aria-label="Previous"><span aria-hidden="true">&laquo;</span></a>
            </li>`;
        const maxPages = 5;
        const startPage = Math.max(1, currentPage - Math.floor(maxPages / 2));
        const endPage = Math.min(totalPages, startPage + maxPages - 1);
        for (let i = startPage; i <= endPage; i++) {
            html += `<li class="page-item ${i === currentPage ? 'active' : ''}"><a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
        }
        html += `
            <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage + 1}" aria-label="Next"><span aria-hidden="true">&raquo;</span></a>
            </li>`;
        $('#dataPagination').html(html);
    }

    // Helper: compute and update clear-all button without reloading
    function recomputeAndUpdateClearAll(tab) {
        if (tab === 'persistent') {
            const total = $('#persistent-data-container .solution-card[data-item-type="persistent"]').length +
                          $('#persistent-data-container .solution-card[data-item-type="persistent-group"]').length;
            updateClearAllButton('persistent', total);
        } else {
            const total = $('#non-persistent-data-container .solution-card[data-item-type="non-persistent"]').length;
            updateClearAllButton('non-persistent', total);
        }
    }

    // Helper: show empty-state message if a tab becomes empty
    function maybeShowEmptyState(tab) {
        if (tab === 'persistent') {
            const total = $('#persistent-data-container .solution-card[data-item-type="persistent"]').length +
                          $('#persistent-data-container .solution-card[data-item-type="persistent-group"]').length;
            if (total === 0) {
                $('#persistent-data-container').html(`
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle"></i> No persistent data found for the selected filter.
                    </div>
                `);
            }
        } else {
            const total = $('#non-persistent-data-container .solution-card[data-item-type="non-persistent"]').length;
            if (total === 0) {
                $('#non-persistent-data-container').html(`
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle"></i> <strong>No non-persistent data found.</strong>
                        <br><small>This is good! Either all your work is already persistent, or you haven't saved any solutions/notes with auto-persist disabled.</small>
                        <br><small>To see items here: turn off auto-persist toggles in the Problems page, then save solutions or notes.</small>
                    </div>
                `);
            }
        }
    }

    // Helper: remove a card smoothly and update state
    function removeCardAndUpdate(tab, card) {
        if (!card || card.length === 0) return;
        card.fadeOut(150, function() {
            $(this).remove();
            recomputeAndUpdateClearAll(tab);
            maybeShowEmptyState(tab);
        });
    }

    function deletePersistentData(id) {
        $.ajax({ url: `/api/persistent_data/${id}`, method: 'DELETE' })
          .done(function(response){
              if (response.success) {
                  const card = $(`.solution-card[data-id="${id}"][data-item-type="persistent"]`);
                  if (card.length) { removeCardAndUpdate('persistent', card); } else { loadPersistentData(currentPage, currentFilter); }
                  showTemporaryMessage('Data deleted successfully.', 'success');
              } else {
                  showTemporaryMessage(`Error: ${response.error}`, 'error');
              }
          })
          .fail(function(xhr){ const msg = buildErrorMessage(xhr, 'Error deleting data.', 'owner'); showTemporaryMessage(msg, 'error'); });
    }
    
    function clearNonPersistentData(id, dataType, noteType) {
        let url; let data = {};
        if (dataType === 'solution') {
            const currentItem = $('.solution-card').filter(`[data-id="${id}"]`);
            const stopId = currentItem.data('stop-id');
            url = '/api/save_solution';
            data = { problem_id: stopId || id, problem_type: 'any', solution: '' };
        } else if (dataType === 'note') {
            url = `/api/user_notes/${id}`; data = {};
        }
        $.ajax({ url: url, method: dataType === 'note' ? 'DELETE' : 'POST', contentType: 'application/json', data: JSON.stringify(data) })
          .done(function(response){
              if (response.success) {
                  showTemporaryMessage('Data cleared successfully.', 'success');
                  const card = $(`.solution-card[data-id="${id}"][data-item-type="non-persistent"]`);
                  if (card.length) { removeCardAndUpdate('non-persistent', card); } else { loadNonPersistentData(currentPage, currentFilter); }
              } else {
                  showTemporaryMessage(`Error: ${response.error}`, 'error');
              }
          })
          .fail(function(xhr){ const msg = buildErrorMessage(xhr, 'Error clearing data.', null); showTemporaryMessage(msg, 'error'); });
    }

    function makePersistent(id, dataType, noteType, problemType) {
        const url = dataType === 'note' ? `/api/make_note_persistent/${noteType}` : '/api/make_solution_persistent';
        let payload = {};
        if (dataType === 'solution') {
            payload = { problem_id: id, problem_type: problemType };
        } else {
            const btn = $(`.make-persistent-btn[data-id="${id}"][data-data-type="note"]`);
            const sloid = btn.data('sloid');
            const osmNodeId = btn.data('osm-node-id');
            payload = { sloid: noteType === 'atlas' ? (sloid || null) : undefined, osm_node_id: noteType === 'osm' ? (osmNodeId || null) : undefined };
        }
        $.ajax({ url: url, method: 'POST', contentType: 'application/json', data: JSON.stringify(payload) })
          .done(function(response){
              if (response.success) {
                  if (currentTab === 'non-persistent') {
                      const card = $(`.solution-card[data-id="${id}"][data-item-type="non-persistent"]`);
                      if (card.length) { removeCardAndUpdate('non-persistent', card); } else { loadNonPersistentData(currentPage, currentFilter); }
                  } else if (currentTab === 'persistent') {
                      loadPersistentData(currentPage, currentFilter);
                  }
                  showTemporaryMessage('Data made persistent successfully!', 'success');
              } else {
                  showTemporaryMessage(`Error: ${response.error}`, 'error');
              }
          })
          .fail(function(xhr){ const msg = buildErrorMessage(xhr, 'Error making data persistent.', 'persist'); showTemporaryMessage(msg, 'error'); });
    }

    function makeNonPersistent(id, type) {
        $.ajax({ url: `/api/make_non_persistent/${id}`, method: 'POST', contentType: 'application/json', data: JSON.stringify({ type: type }) })
          .done(function(response){
              if (response.success) {
                  showTemporaryMessage('Data successfully made non-persistent.', 'success');
                  const card = $(`.solution-card[data-id="${id}"][data-item-type="persistent"]`);
                  if (card.length) { removeCardAndUpdate('persistent', card); } else { loadPersistentData(currentPage, currentFilter); }
              } else {
                  showTemporaryMessage(`Error: ${response.error}`, 'error');
              }
          })
          .fail(function(xhr){ const msg = buildErrorMessage(xhr, 'An error occurred while making the data non-persistent.', 'owner'); showTemporaryMessage(msg, 'error'); });
    }

    function clearAllData(tab) {
        $.ajax({ url: `/api/clear_all_${tab}`, method: 'POST' })
          .done(function(response){ if (response.success) { showTemporaryMessage(`All ${tab} data has been cleared.`, 'success'); if (tab === 'persistent') { loadPersistentData(1, 'all'); } else { loadNonPersistentData(1, 'all'); } } else { showTemporaryMessage(`Error: ${response.error}`, 'error'); } })
          .fail(function(xhr){ const msg = buildErrorMessage(xhr, `An error occurred while clearing ${tab} data.`, 'bulk'); showTemporaryMessage(msg, 'error'); });
    }

    function showTemporaryMessage(message, type) { SharedUtils.showTemporaryMessage(message, type, 5000); }
    function updateClearAllButton(tab, totalItems) {
        const container = $(`#clear-all-${tab}-container`);
        container.empty();
        if (totalItems > 0 && isAdmin) {
            const buttonHtml = `
                <button class="btn btn-outline-danger btn-sm clear-all-btn" data-tab="${tab}">
                    <i class="fas fa-exclamation-triangle"></i> Clear all ${tab.replace('-', ' ')} data
                </button>`;
            container.html(buttonHtml);
        }
    }

    // Initialize the page
    initializeManageDataPage();
}); 


