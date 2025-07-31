// persistent-data.js - JavaScript for the Persistent Data Management Page

$(document).ready(function() {
    let currentPage = 1;
    let currentFilter = 'all';
    let currentTab = 'persistent'; // 'persistent' or 'non-persistent'
    
    // Initialize the persistent data page
    function initializePersistentDataPage() {
        // Load initial data based on current tab
        if (currentTab === 'persistent') {
            loadPersistentData(currentPage, currentFilter);
        } else {
            loadNonPersistentData(currentPage, currentFilter);
        }
        
        // Setup event handlers
        setupEventHandlers();
    }
    
    // Setup all event handlers
    function setupEventHandlers() {
        // Tab switching
        $('.nav-link[data-toggle="tab"]').on('shown.bs.tab', function(e) {
            const targetTab = $(e.target).attr('href').substring(1); // Remove #
            currentTab = targetTab;
            currentPage = 1; // Reset pagination
            
            if (currentTab === 'persistent') {
                loadPersistentData(currentPage, currentFilter);
            } else {
                loadNonPersistentData(currentPage, currentFilter);
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
            const id = $(this).data('id');
            const dataType = $(this).data('data-type'); // 'solution' or 'note'
            const noteType = $(this).data('note-type'); // 'atlas' or 'osm' for notes
            makePersistent(id, dataType, noteType);
        });

        // Make all persistent button handler
        $('#makeAllPersistentBtn').on('click', function() {
            makeAllPersistent();
        });
    }
    
    // Load persistent data (existing functionality)
    function loadPersistentData(page = 1, filter = 'all') {
        $('#dataContainer').html(`
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
        
        $.getJSON('/api/persistent_data', params, function(data) {
            if (data.persistent_data.length === 0) {
                $('#dataContainer').html(`
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle"></i> No persistent data found.
                    </div>
                `);
                $('#dataPagination').empty();
                return;
            }
            
            let html = '';
            data.persistent_data.forEach(item => {
                html += renderPersistentDataItem(item);
            });
            $('#dataContainer').html(html);
            
            // Generate pagination
            generatePagination(data.page, Math.ceil(data.total / data.limit));
        }).fail(function() {
            $('#dataContainer').html(`
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i> Error loading persistent data.
                </div>
            `);
        });
    }
    
    // Load non-persistent data (new functionality)
    function loadNonPersistentData(page = 1, filter = 'all') {
        $('#dataContainer').html(`
            <div class="text-center py-5">
                <div class="spinner-border" role="status">
                    <span class="sr-only">Loading...</span>
                </div>
                <p class="mt-2">Loading non-persistent data...</p>
            </div>
        `);
        
        const params = { page: page, limit: 10, filter: filter };
        
        $.getJSON('/api/non_persistent_data', params, function(data) {
            if (data.data.length === 0) {
                $('#dataContainer').html(`
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
            $('#dataContainer').html(html);
            
            // Generate pagination
            generatePagination(data.page, Math.ceil(data.total / data.limit));
        }).fail(function() {
            $('#dataContainer').html(`
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i> Error loading non-persistent data.
                </div>
            `);
        });
    }
    
    // Render persistent data item
    function renderPersistentDataItem(item) {
        // Determine if this is a problem solution or a note
        const isNote = item.note_type === 'atlas' || item.note_type === 'osm';
        
        let cardClass, badgeClass, titleText;
        
        if (isNote) {
            // Handle notes
            if (item.note_type === 'atlas') {
                cardClass = 'atlas_note';
                badgeClass = 'info';
                titleText = 'ATLAS Note';
            } else {
                cardClass = 'osm_note';
                badgeClass = 'primary';
                titleText = 'OSM Note';
            }
        } else {
            // Handle problem solutions
            cardClass = item.problem_type;
            badgeClass = item.problem_type === 'distance' ? 'danger' : 
                        item.problem_type === 'isolated' ? 'warning' : 
                        item.problem_type === 'attributes' ? 'info' : 'secondary';
            titleText = item.problem_type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        }
        
        const formattedDate = new Date(item.updated_at).toLocaleString();
        
        return `
            <div class="card solution-card ${cardClass}" data-id="${item.id}">
                <div class="card-body">
                    <div class="solution-header">
                        <h5 class="card-title">
                            <span class="badge badge-${badgeClass}">
                                ${titleText}
                            </span>
                        </h5>
                        <button class="btn btn-sm btn-outline-danger delete-solution-btn" data-id="${item.id}" data-type="persistent">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                    
                    <div class="card-text">
                        <div><strong>SLOID:</strong> ${item.sloid || '<em>None</em>'}</div>
                        <div><strong>OSM Node ID:</strong> ${item.osm_node_id || '<em>None</em>'}</div>
                        <div><strong>Last Updated:</strong> ${formattedDate}</div>
                        
                        <div class="solution-content">
                            <strong>${isNote ? 'Note:' : 'Solution:'}</strong> ${isNote ? item.note : item.solution}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
    
    // Render non-persistent data item
    function renderNonPersistentDataItem(item) {
        const isNote = item.type === 'note';
        
        let cardClass, badgeClass, titleText;
        
        if (isNote) {
            if (item.note_type === 'atlas') {
                cardClass = 'atlas_note';
                badgeClass = 'info';
                titleText = 'ATLAS Note';
            } else {
                cardClass = 'osm_note';
                badgeClass = 'primary';
                titleText = 'OSM Note';
            }
        } else {
            cardClass = item.problem_type;
            badgeClass = item.problem_type === 'distance' ? 'danger' : 
                        item.problem_type === 'isolated' ? 'warning' : 
                        item.problem_type === 'attributes' ? 'info' : 'secondary';
            titleText = item.problem_type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        }
        
        return `
            <div class="card solution-card ${cardClass}" data-id="${item.id}" ${!isNote ? `data-stop-id="${item.stop_id}"` : ''}>
                <div class="card-body">
                    <div class="solution-header">
                        <h5 class="card-title">
                            <span class="badge badge-${badgeClass}">
                                ${titleText}
                            </span>
                        </h5>
                        <div class="btn-group">
                            <button class="btn btn-sm btn-outline-success make-persistent-btn" 
                                    data-id="${item.id}" 
                                    data-data-type="${isNote ? 'note' : 'solution'}"
                                    ${isNote ? `data-note-type="${item.note_type}"` : ''}>
                                <i class="fas fa-thumbtack"></i> Make Persistent
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-solution-btn" 
                                    data-id="${item.id}" 
                                    data-type="non-persistent"
                                    data-data-type="${isNote ? 'note' : 'solution'}"
                                    ${isNote ? `data-note-type="${item.note_type}"` : ''}>
                                <i class="fas fa-undo"></i> Clear
                            </button>
                        </div>
                    </div>
                    
                    <div class="card-text">
                        <div><strong>SLOID:</strong> ${item.sloid || '<em>None</em>'}</div>
                        <div><strong>OSM Node ID:</strong> ${item.osm_node_id || '<em>None</em>'}</div>
                        
                        <div class="solution-content">
                            <strong>${isNote ? 'Note:' : 'Solution:'}</strong> ${isNote ? item.note : item.solution}
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
    
    // Delete persistent data
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
    function makePersistent(id, dataType, noteType) {
        const url = dataType === 'note' ? 
                   `/api/make_note_persistent/${noteType}` : 
                   '/api/make_solution_persistent';
        
        $.ajax({
            url: url,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                problem_id: id, // Use problem_id for solutions
                sloid: noteType === 'atlas' ? id.replace('atlas_', '') : undefined,
                osm_node_id: noteType === 'osm' ? id.replace('osm_', '') : undefined,
                problem_type: 'any' // Not strictly needed, but good for context
            }),
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
    
    // Initialize the page
    initializePersistentDataPage();
}); 