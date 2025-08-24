// Report Generation Functionality

// Function to initialize report generation features
function initReportGeneration() {
    // On index page, navigate to the dedicated Reports page
    $('#generateReportBtn').on('click', function(){
        window.location.href = '/reports';
    });
    
    // Initialize operator dropdown in reports page if present
    if (document.getElementById('atlasOperatorFilterReports')) {
        window.operatorDropdownReports = new OperatorDropdown('#atlasOperatorFilterReports', {
            placeholder: 'Select operators...',
            multiple: true,
            onSelectionChange: function(selectedOperators) {
                // no immediate action; used when submitting
            }
        });
    }

    // Toggle sections based on category selection
    function updateCategoryVisibility() {
        var cat = $('input[name="reportCategory"]:checked').val();
        $('#unmatchedOptions').toggle(cat === 'unmatched');
        $('#problemsOptions').toggle(cat === 'problems');
    }
    $(document).on('change', 'input[name="reportCategory"]', updateCategoryVisibility);
    updateCategoryVisibility();

    // Global variables for progress tracking
    window.currentTaskId = null;
    window.progressInterval = null;

    // Handle the report form submission
    $('#reportForm').on('submit', function(e){
        e.preventDefault();
        
        // Show loading overlay and reset state
        resetProgressOverlay();
        $('#reportLoadingOverlay').show();
        
        // Build params from form
        var category = $('input[name="reportCategory"]:checked').val();
        var params = {
            limit: ($('input[name="limitMode"]:checked').val() === 'all') ? 'all' : ($('#reportLimitModal').val() || 'all'),
            sort: $('#sortOrderModal').val(),
            report_type: category,
            format: $('#reportFormatModal').val()
        };

        // Operator filter
        if (window.operatorDropdownReports) {
            var ops = window.operatorDropdownReports.getSelection();
            if (ops && ops.length > 0) { params.atlas_operator = ops.join(','); }
        }

        if (category === 'unmatched') {
            var includeAtlas = $('#sourceAtlas').is(':checked');
            var includeOsm = $('#sourceOsm').is(':checked');
            var sources = [];
            if (includeAtlas) sources.push('atlas');
            if (includeOsm) sources.push('osm');
            if (sources.length === 0) { sources = ['atlas','osm']; }
            params.sources = sources.join(',');
        } else if (category === 'problems') {
            // Problem types
            var ptypes = [];
            if ($('#ptypeDistance').is(':checked')) ptypes.push('distance');
            if ($('#ptypeUnmatched').is(':checked')) ptypes.push('unmatched');
            if ($('#ptypeAttributes').is(':checked')) ptypes.push('attributes');
            if ($('#ptypeDuplicates').is(':checked')) ptypes.push('duplicates');
            if (ptypes.length > 0) params.problem_types = ptypes.join(',');

            // Priorities
            var pris = [];
            if ($('#priority1').is(':checked')) pris.push('1');
            if ($('#priority2').is(':checked')) pris.push('2');
            if ($('#priority3').is(':checked')) pris.push('3');
            if (pris.length > 0) params.priorities = pris.join(',');

            // Status
            var statuses = [];
            if ($('#statusSolved').is(':checked')) statuses.push('solved');
            if ($('#statusUnsolved').is(':checked')) statuses.push('unsolved');
            if (statuses.length > 0) params.solution_status = statuses.join(',');
        }

        // Start async report generation
        startAsyncReportGeneration(params);
        
        // Hide the modal
        try { $('#reportModal').modal('hide'); } catch (e) {}
    });

    // Enable/disable limit input based on mode
    $(document).on('change', 'input[name="limitMode"]', function() {
        var mode = $('input[name="limitMode"]:checked').val();
        if (mode === 'upto') { $('#reportLimitModal').prop('disabled', false); }
        else { $('#reportLimitModal').prop('disabled', true); }
    });
    function resetProgressOverlay() {
        $('#reportProgressBar').css('width', '0%').attr('aria-valuenow', 0);
        $('#progressText').text('Starting...');
        $('#entriesProcessed').text('0');
        $('#totalEntries').text('0');
        $('#etaText').hide();
        $('#downloadSection').hide();
        $('#errorSection').hide();
        $('#progressControls').show();
    }

    function startAsyncReportGeneration(params) {
        $.ajax({
            url: '/api/generate_report_async',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(params),
            success: function(response) {
                if (response.task_id) {
                    window.currentTaskId = response.task_id;
                    startProgressPolling();
                } else {
                    showError('Failed to start report generation');
                }
            },
            error: function(xhr) {
                var error = 'Unknown error';
                try {
                    var response = JSON.parse(xhr.responseText);
                    error = response.error || error;
                } catch (e) {}
                showError('Error starting report: ' + error);
            }
        });
    }

    function startProgressPolling() {
        if (window.progressInterval) {
            clearInterval(window.progressInterval);
        }
        
        window.progressInterval = setInterval(function() {
            if (!window.currentTaskId) return;
            
            $.ajax({
                url: '/api/report_progress/' + window.currentTaskId,
                method: 'GET',
                success: function(progress) {
                    updateProgress(progress);
                },
                error: function() {
                    // Continue polling unless specifically cancelled
                    if (window.currentTaskId) {
                        console.log('Progress polling error, continuing...');
                    }
                }
            });
        }, 500);
    }

    function updateProgress(progress) {
        if (!progress) return;
        
        var processed = progress.processed || 0;
        var total = progress.total || 0;
        var status = progress.status;
        
        // Update counters
        $('#entriesProcessed').text(processed.toLocaleString());
        $('#totalEntries').text(total.toLocaleString());
        
        // Update progress bar
        var percentage = total > 0 ? Math.round((processed / total) * 100) : 0;
        $('#reportProgressBar').css('width', percentage + '%').attr('aria-valuenow', percentage);
        
        if (status === 'starting') {
            $('#progressText').text('Starting...');
        } else if (status === 'processing') {
            $('#progressText').text(percentage + '%');
            
            // Show ETA if available
            if (progress.eta && progress.eta > 0) {
                var eta = Math.round(progress.eta);
                var etaText = eta < 60 ? eta + 's' : Math.round(eta/60) + 'm ' + (eta%60) + 's';
                $('#etaValue').text(etaText);
                $('#etaText').show();
            }
        } else if (status === 'completed') {
            $('#progressText').text('100%');
            $('#reportProgressBar').css('width', '100%').attr('aria-valuenow', 100);
            stopProgressPolling();
            showDownloadButton();
        } else if (status === 'error') {
            stopProgressPolling();
            showError(progress.error || 'Unknown error occurred');
        }
    }

    function showDownloadButton() {
        $('#progressControls').hide();
        $('#downloadSection').show();
        
        $('#downloadReportBtn').off('click').on('click', function() {
            if (window.currentTaskId) {
                window.location.href = '/api/download_report/' + window.currentTaskId;
                // Hide overlay after download starts
                setTimeout(function() {
                    cancelReportGeneration();
                }, 1000);
            }
        });
    }

    function showError(message) {
        $('#progressControls').hide();
        $('#errorMessage').text(message);
        $('#errorSection').show();
    }

    function stopProgressPolling() {
        if (window.progressInterval) {
            clearInterval(window.progressInterval);
            window.progressInterval = null;
        }
    }
}

// Function to cancel report generation
function cancelReportGeneration() {
    // Cancel on backend if task is running
    if (window.currentTaskId) {
        $.ajax({
            url: '/api/cancel_report/' + window.currentTaskId,
            method: 'POST',
            complete: function() {
                window.currentTaskId = null;
            }
        });
    }
    
    // Stop polling and hide overlay
    if (window.progressInterval) {
        clearInterval(window.progressInterval);
        window.progressInterval = null;
    }
    
    $('#reportLoadingOverlay').hide();
}

// Export functions for use in main.js
window.initReportGeneration = initReportGeneration;
window.cancelReportGeneration = cancelReportGeneration; 