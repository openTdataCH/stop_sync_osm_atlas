// persistent-data.js - JavaScript for the Persistent Data Management Page

$(document).ready(function() {
    // Expose CSRF token for AJAX (Flask-WTF sets this cookie header by default when using CSRFProtect with AJAX)
    const csrfToken = (document.cookie.match(/\bcsrf_token=([^;]+)/) || [])[1];
    if (csrfToken) {
        $.ajaxSetup({
            headers: { 'X-CSRFToken': csrfToken }
        });
    }

    let currentPage = 1;
    let currentFilter = 'all';
    let currentTab = 'persistent'; // 'persistent' or 'non-persistent'
    let isAdmin = false;
    
    // Initialize the persistent data page with proper error handling
    function initializePersistentDataPage() {
        try {
            // Setup event handlers first
            setupEventHandlers();
            
            // Load initial data for the default tab (persistent), but first detect admin
            if (window.__authStatusEndpoint) {
                $.getJSON(window.__authStatusEndpoint, function(status){
                    isAdmin = !!(status && status.is_admin);
                    loadPersistentData(currentPage, currentFilter);
                }).fail(function(){
                    loadPersistentData(currentPage, currentFilter);
                });
            } else {
                loadPersistentData(currentPage, currentFilter);
            }
        } catch (error) {
            console.error('Error initializing persistent data page:', error);
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

        // Handler for making persistent data non-persistent
        $(document).on('click', '.make-non-persistent-btn', function() {
            const id = $(this).data('id');
            const type = $(this).data('type'); // 'solution' or 'note'
            makeNonPersistent(id, type);
        });

        // Handler for clearing all data in a tab
        $(document).on('click', '.clear-all-btn', function() {
            const tab = $(this).data('tab');
            if (confirm(`Are you sure you want to clear all ${tab} data? This action cannot be undone.`)) {
                clearAllData(tab);
            }
        });
    }
    
    // Load persistent data with improved error handling and clearer loading states
    function loadPersistentData(page = 1, filter = 'all') {
        const container = $('#persistent-data-container');
        container.html(`
            <div class="text-center py-5">
                <div class="spinner-border" role="status">
                    <span class="sr-only">Loading...</span>
                </div>
                <p class="mt-2">Loading persistent data...</p>
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
                if (!data.persistent_data || data.persistent_data.length === 0) {
                    container.html(`
                        <div class="alert alert-warning">
                            <i class="fas fa-exclamation-triangle"></i> No persistent data found for the selected filter.
                        </div>
                    `);
                    $('#dataPagination').empty();
                    return;
                }
                
                let html = '';
                data.persistent_data.forEach(item => {
                    html += renderPersistentDataItem(item);
                });
                container.html(html);
                
                // Generate pagination
                generatePagination(data.page, Math.ceil(data.total / data.limit));

                // Add Clear All button
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
    
    // Load non-persistent data with improved performance and error handling
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
                    // Ensure we always use the non-persistent rendering function for this tab
                    html += renderNonPersistentDataItem(item);
                });
                container.html(html);
                
                // Generate pagination
                generatePagination(data.page, Math.ceil(data.total / data.limit));

                // Add Clear All button
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
    
    // Render persistent data item - should ONLY show delete button
    function renderPersistentDataItem(item) {
        if (!item || !item.id) {
            console.error('Invalid item passed to renderPersistentDataItem:', item);
            return '';
        }
        
        // Determine if this is a problem solution or a note
        const isNote = item.note_type === 'atlas' || item.note_type === 'osm';
        
        let cardClass, badgeClass, titleText;
        
        if (isNote) {
            // Handle notes
            if (item.note_type === 'atlas') {
                cardClass = 'atlas_note';
                badgeClass = 'info';
                titleText = 'ATLAS Note';
            } else if (item.note_type === 'osm') {
                cardClass = 'osm_note';
                badgeClass = 'primary';
                titleText = 'OSM Note';
            } else {
                cardClass = 'unknown_note';
                badgeClass = 'secondary';
                titleText = 'Unknown Note';
            }
        } else {
            // Handle problem solutions
            cardClass = item.problem_type || 'unknown';
            badgeClass = item.problem_type === 'distance' ? 'danger' : 
                        item.problem_type === 'isolated' ? 'warning' : 
                        item.problem_type === 'attributes' ? 'info' : 'secondary';
            titleText = (item.problem_type || 'Unknown').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        }
        
        const formattedDate = item.updated_at ? new Date(item.updated_at).toLocaleString() : 'Unknown';
        const content = isNote ? (item.note || '') : (item.solution || '');
        
        const authorLine = (item.author_email && item.author_email.trim().length > 0) ? `<div><strong>Author:</strong> ${item.author_email}</div>` : `<div><strong>Author:</strong> <em>Not a user</em></div>`;
        const adminButtons = isAdmin ? `
                        <div class="btn-group">
                             <button class="btn btn-sm btn-warning make-non-persistent-btn" 
                                    data-id="${item.id}" 
                                    data-type="${isNote ? 'note' : 'solution'}">
                                <i class="fas fa-undo"></i> Make Non-Persistent
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-solution-btn" 
                                    data-id="${item.id}"
                                    data-type="persistent">
                                <i class="fas fa-trash"></i> Clear
                            </button>
                        </div>` : '';
        return `
            <div class="card solution-card ${cardClass}" data-id="${item.id}" data-item-type="persistent">
                <div class="card-body">
                    <div class="solution-header">
                        <h5 class="card-title">
                            <span class="badge badge-${badgeClass}">
                                ${titleText}
                            </span>
                            <small class="text-muted ml-2">Persistent</small>
                        </h5>
                        ${adminButtons}
                    </div>
                    
                    <div class="card-text">
                        <div><strong>SLOID:</strong> ${item.sloid || '<em>None</em>'}</div>
                        <div><strong>OSM Node ID:</strong> ${item.osm_node_id || '<em>None</em>'}</div>
                        ${authorLine}
                        <div><strong>Last Updated:</strong> ${formattedDate}</div>
                        
                        <div class="solution-content">
                            <strong>${isNote ? 'Note:' : 'Solution:'}</strong> ${content || '<em>Empty</em>'}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
    
    // Render non-persistent data item - should ONLY show make persistent and clear buttons
    function renderNonPersistentDataItem(item) {
        if (!item || !item.id) {
            console.error('Invalid item passed to renderNonPersistentDataItem:', item);
            return '';
        }
        
        const isNote = item.type === 'note';
        
        let cardClass, badgeClass, titleText;
        
        if (isNote) {
            if (item.note_type === 'atlas') {
                cardClass = 'atlas_note';
                badgeClass = 'info';
                titleText = 'ATLAS Note';
            } else if (item.note_type === 'osm') {
                cardClass = 'osm_note';
                badgeClass = 'primary';
                titleText = 'OSM Note';
            } else {
                cardClass = 'unknown_note';
                badgeClass = 'secondary';
                titleText = 'Unknown Note';
            }
        } else {
            cardClass = item.problem_type || 'unknown';
            badgeClass = item.problem_type === 'distance' ? 'danger' : 
                        item.problem_type === 'isolated' ? 'warning' : 
                        item.problem_type === 'attributes' ? 'info' : 'secondary';
            titleText = (item.problem_type || 'Unknown').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        }
        
        const content = isNote ? (item.note || '') : (item.solution || '');
        
        return `
            <div class="card solution-card ${cardClass}" data-id="${item.id}" data-item-type="non-persistent" ${!isNote ? `data-stop-id="${item.stop_id}"` : ''}>
                <div class="card-body">
                    <div class="solution-header">
                        <h5 class="card-title">
                            <span class="badge badge-${badgeClass}">
                                ${titleText}
                            </span>
                            <small class="text-muted ml-2">Temporary</small>
                        </h5>
                        <div class="btn-group">
                            <button class="btn btn-sm btn-outline-success make-persistent-btn" 
                                    data-id="${item.id}" 
                                    data-data-type="${isNote ? 'note' : 'solution'}"
                                    ${isNote ? `data-note-type="${item.note_type}"` : ''}
                                    ${!isNote ? `data-problem-type="${item.problem_type}"` : ''}>
                                <i class="fas fa-thumbtack"></i> Make Persistent
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-solution-btn" 
                                    data-id="${item.id}" 
                                    data-type="non-persistent"
                                    data-data-type="${isNote ? 'note' : 'solution'}"
                                    ${isNote ? `data-note-type="${item.note_type}"` : ''}>
                                <i class="fas fa-trash"></i> Clear
                            </button>
                        </div>
                    </div>
                    
                    <div class="card-text">
                        <div><strong>SLOID:</strong> ${item.sloid || '<em>None</em>'}</div>
                        <div><strong>OSM Node ID:</strong> ${item.osm_node_id || '<em>None</em>'}</div>
                        
                        <div class="solution-content">
                            <strong>${isNote ? 'Note:' : 'Solution:'}</strong> ${content || '<em>Empty</em>'}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
    
    // Generate pagination links
    function generatePagination(currentPage, totalPages) {
        if (totalPages <= 1) {
            $('#dataPagination').empty();
            return;
        }
        
        let html = `
            <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage - 1}" aria-label="Previous">
                    <span aria-hidden="true">&laquo;</span>
                </a>
            </li>
        `;
        
        const maxPages = 5;
        const startPage = Math.max(1, currentPage - Math.floor(maxPages / 2));
        const endPage = Math.min(totalPages, startPage + maxPages - 1);
        
        for (let i = startPage; i <= endPage; i++) {
            html += `
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `;
        }
        
        html += `
            <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage + 1}" aria-label="Next">
                    <span aria-hidden="true">&raquo;</span>
                </a>
            </li>
        `;
        
        $('#dataPagination').html(html);
    }
    
        // Delete persistent data (admin only)
    function deletePersistentData(id) {
        $.ajax({
            url: `/api/persistent_data/${id}`,
            method: 'DELETE',
            success: function(response) {
                if (response.success) {
                    // Reload the current page
                    loadPersistentData(currentPage, currentFilter);
                    
                    // Show success message
                    showTemporaryMessage('Data deleted successfully.', 'success');
                } else {
                    showTemporaryMessage(`Error: ${response.error}`, 'error');
                }
            },
            error: function() {
                showTemporaryMessage('Error deleting data.', 'error');
            }
        });
    }
    
    // Clear non-persistent data
    function clearNonPersistentData(id, dataType, noteType) {
        let url;
        let data = {};

        if (dataType === 'solution') {
            // For solutions, we need to find the corresponding item from the current page data
            // to get the stop_id instead of using the problem id directly
            const currentItem = $('.solution-card').filter(`[data-id="${id}"]`);
            const stopId = currentItem.data('stop-id');
            
            url = '/api/save_solution';
            data = {
                problem_id: stopId || id, // Use stop_id if available, fallback to id
                problem_type: 'any', // Backend will find it
                solution: ''
            };
        } else if (dataType === 'note') {
            url = `/api/save_note/${noteType}`;
            if (noteType === 'atlas') {
                data.sloid = id.replace('atlas_', '');
            } else {
                data.osm_node_id = id.replace('osm_', '');
            }
            data.note = '';
        }

        $.ajax({
            url: url,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(data),
            success: function(response) {
                if (response.success) {
                    showTemporaryMessage('Data cleared successfully.', 'success');
                    loadNonPersistentData(currentPage, currentFilter);
                } else {
                    showTemporaryMessage(`Error: ${response.error}`, 'error');
                }
            },
            error: function() {
                showTemporaryMessage('Error clearing data.', 'error');
            }
        });
    }
    
    // Make data persistent
    function makePersistent(id, dataType, noteType, problemType) {
        const url = dataType === 'note' ? 
                   `/api/make_note_persistent/${noteType}` : 
                   '/api/make_solution_persistent';
        
        let payload = {};
        if (dataType === 'solution') {
            payload = {
                problem_id: id, // This is now stop_id
                problem_type: problemType
            };
        } else {
            payload = {
                sloid: noteType === 'atlas' ? id.replace('atlas_', '') : undefined,
                osm_node_id: noteType === 'osm' ? id.replace('osm_', '') : undefined
            };
        }

        $.ajax({
            url: url,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            success: function(response) {
                if (response.success) {
                    // Reload current tab
                    if (currentTab === 'persistent') {
                        loadPersistentData(currentPage, currentFilter);
                    } else {
                        loadNonPersistentData(currentPage, currentFilter);
                    }
                    
                    showTemporaryMessage('Data made persistent successfully!', 'success');
                } else {
                    showTemporaryMessage(`Error: ${response.error}`, 'error');
                }
            },
            error: function() {
                showTemporaryMessage('Error making data persistent.', 'error');
            }
        });
    }
    
        // Make a persistent item non-persistent (admin only)
    function makeNonPersistent(id, type) {
        $.ajax({
            url: `/api/make_non_persistent/${id}`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ type: type }),
            success: function(response) {
                if (response.success) {
                    showTemporaryMessage('Data successfully made non-persistent.', 'success');
                    loadPersistentData(currentPage, currentFilter);
                } else {
                    showTemporaryMessage(`Error: ${response.error}`, 'error');
                }
            },
            error: function() {
                showTemporaryMessage('An error occurred while making the data non-persistent.', 'error');
            }
        });
    }

        // Clear all data for a specific tab (admin only)
    function clearAllData(tab) {
        $.ajax({
            url: `/api/clear_all_${tab}`,
            method: 'POST',
            success: function(response) {
                if (response.success) {
                    showTemporaryMessage(`All ${tab} data has been cleared.`, 'success');
                    if (tab === 'persistent') {
                        loadPersistentData(1, 'all');
                    } else {
                        loadNonPersistentData(1, 'all');
                    }
                } else {
                    showTemporaryMessage(`Error: ${response.error}`, 'error');
                }
            },
            error: function() {
                showTemporaryMessage(`An error occurred while clearing ${tab} data.`, 'error');
            }
        });
    }

    // Make all current problem solutions and notes persistent
    function makeAllPersistent() {
        // Get count of non-persistent items first
        $.getJSON('/api/non_persistent_data', { count_only: true }, function(countData) {
            const solutionCount = countData.solution_count || 0;
            const noteCount = countData.note_count || 0;
            
            if (solutionCount === 0 && noteCount === 0) {
                showTemporaryMessage('No non-persistent data found. All your work is already persistent! <i class="fas fa-database"></i>', 'info');
                return;
            }
            
            let confirmMessage = 'Make ';
            if (solutionCount > 0) {
                confirmMessage += `${solutionCount} problem solution${solutionCount > 1 ? 's' : ''}`;
            }
            if (noteCount > 0) {
                if (solutionCount > 0) confirmMessage += ' and ';
                confirmMessage += `${noteCount} note${noteCount > 1 ? 's' : ''}`;
            }
            confirmMessage += ' persistent? This action can be undone by deleting them from the persistent data tab.';
            
            if (!confirm(confirmMessage)) {
                return;
            }
            
            const button = $('#makeAllPersistentBtn');
            const originalButtonHtml = button.html();
            button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Processing...');
            
            $.ajax({
                url: '/api/make_all_persistent',
                method: 'POST',
                success: function(response) {
                    if (response.success) {
                        showTemporaryMessage(`Batch operation complete: ${response.solutions_made_persistent} solutions and ${response.notes_made_persistent} notes converted to persistent data! <i class="fas fa-database"></i>`, 'success');
                        
                        // Reload current view
                        loadNonPersistentData(currentPage, currentFilter);
                    } else {
                        showTemporaryMessage(`Error: ${response.error}`, 'error');
                    }
                    
                    button.prop('disabled', false).html(originalButtonHtml);
                },
                error: function() {
                    showTemporaryMessage('Error making data persistent.', 'error');
                    button.prop('disabled', false).html(originalButtonHtml);
                }
            });
        }).fail(function() {
            showTemporaryMessage('Error loading data count.', 'error');
        });
    }
    
    // Show temporary message helper
    function showTemporaryMessage(message, type = 'info') {
        const alertClass = type === 'success' ? 'alert-success' : 
                          type === 'error' ? 'alert-danger' : 
                          type === 'warning' ? 'alert-warning' : 'alert-info';
        
        const icon = type === 'success' ? 'fas fa-check-circle' : 
                    type === 'error' ? 'fas fa-exclamation-circle' : 
                    type === 'warning' ? 'fas fa-exclamation-triangle' : 'fas fa-info-circle';
        
        const alertHtml = `
            <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
                <i class="${icon}"></i> ${message}
                <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>
        `;
        
        $('.container').prepend(alertHtml);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            $('.alert').fadeOut();
        }, 5000);
    }
    
    // Helper function to update the 'Clear All' button
    function updateClearAllButton(tab, totalItems) {
        const container = $(`#clear-all-${tab}-container`);
        container.empty();
        if (totalItems > 0 && isAdmin) {
            const buttonHtml = `
                <button class="btn btn-outline-danger btn-sm clear-all-btn" data-tab="${tab}">
                    <i class="fas fa-exclamation-triangle"></i> Clear all ${tab.replace('-', ' ')} data
                </button>
            `;
            container.html(buttonHtml);
        }
    }

    // Initialize the page
    initializePersistentDataPage();
}); 