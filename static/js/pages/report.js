// Report Generation Functionality

// Global variables for progress tracking
window.currentTaskId = null;
window.progressInterval = null;

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
        $('#progressText').text(percentage + '% complete');
        
        // Show ETA if available
        if (progress.eta && progress.eta > 0) {
            var eta = Math.round(progress.eta);
            var etaText = eta < 60 ? eta + 's' : Math.round(eta/60) + 'm ' + (eta%60) + 's';
            $('#etaValue').text(etaText);
            $('#etaText').show();
        }
    } else if (status === 'completed') {
        $('#progressText').text('Complete!');
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
    if (typeof message !== 'string') {
        message = 'An error occurred during report generation.';
    }
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

// Function to initialize report generation features
function initReportGeneration() {
    // On index page, navigate to the dedicated Insights page (export tab)
    $('#generateReportBtn').on('click', function(){
        window.location.href = '/insights?tab=export';
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
        // Constrain sort options by category
        var $sort = $('#sortOrderModal');
        $sort.find('option').prop('disabled', false).show();
        if (cat === 'distance') {
            // allow operator and distance, hide priority
            $sort.find('option[value^="priority_"]').prop('disabled', true).hide();
        } else if (cat === 'unmatched') {
            // allow operator only
            $sort.find('option[value^="distance_"]').prop('disabled', true).hide();
            $sort.find('option[value^="priority_"]').prop('disabled', true).hide();
        } else if (cat === 'problems') {
            // allow operator and priority, hide distance
            $sort.find('option[value^="distance_"]').prop('disabled', true).hide();
        }
        // If current value is disabled, reset to a valid default
        if ($sort.find('option:selected').is(':disabled')) {
            if (cat === 'distance') {
                $sort.val('distance_desc');
            } else if (cat === 'problems') {
                $sort.val('priority_desc');
            } else {
                $sort.val('operator_asc');
            }
        }
        updateSortHelpAndSummary();
    }
    $(document).on('change', 'input[name="reportCategory"]', updateCategoryVisibility);
    updateCategoryVisibility();

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

        // Include fields
        var includeFields = [];
        if ($('#includeAtlasCoords').is(':checked')) includeFields.push('atlas_coords');
        if ($('#includeOsmCoords').is(':checked')) includeFields.push('osm_coords');
        if (includeFields.length > 0) params.include_fields = includeFields.join(',');

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
        updateSortHelpAndSummary();
    });

    // Update helper text and summary reflecting the current selection
    function updateSortHelpAndSummary() {
        var cat = $('input[name="reportCategory"]:checked').val();
        var sort = $('#sortOrderModal').val();
        var mode = $('input[name="limitMode"]:checked').val();
        var limit = $('#reportLimitModal').val();
        var $limitLabel = $('#limitModeLabelUpto');
        var $sortHelp = $('#sortHelp');
        var $summary = $('#selectionSummary');

        // Label: "Top" when sorting by distance/priority desc, else "First"
        var isTop = (sort === 'distance_desc') || (sort === 'priority_desc');
        if ($limitLabel.length) { $limitLabel.text(isTop ? 'Top' : 'First'); }

        // Help text
        var help = '';
        if (cat === 'distance') {
            if (sort.indexOf('distance_') === 0) help = 'Entries sorted by distance. "Top N" selects closest/farthest.';
            else help = 'Entries sorted by operator alphabetically.';
        } else if (cat === 'unmatched') {
            help = 'Entries sorted by operator alphabetically.';
        } else if (cat === 'problems') {
            if (sort.indexOf('priority_') === 0) help = 'Entries sorted by priority. "Top N" selects highest priority.';
            else help = 'Entries sorted by operator alphabetically.';
        }
        if ($sortHelp.length) { $sortHelp.text(help); }

        // Summary line - more descriptive
        var categoryName = '';
        if (cat === 'distance') categoryName = 'Matched pairs';
        if (cat === 'unmatched') categoryName = 'Unmatched entries';
        if (cat === 'problems') categoryName = 'Problems';
        
        var sortName = '';
        if (sort.indexOf('operator_') === 0) sortName = 'operator';
        if (sort.indexOf('distance_') === 0) sortName = 'distance';
        if (sort.indexOf('priority_') === 0) sortName = 'priority';
        
        var direction = sort.endsWith('_asc') ? 'ascending' : 'descending';
        
        var summary = categoryName + ' sorted by ' + sortName + ' (' + direction + ')';
        if (mode === 'upto') {
            summary += ', ' + (isTop ? 'top' : 'first') + ' ' + (limit || 'N') + ' entries';
        }
        if ($summary.length) { $summary.text(summary); }
    }

    // React on sort, limit, category changes
    $(document).on('change', '#sortOrderModal, #reportLimitModal, input[name="reportCategory"]', updateSortHelpAndSummary);
    // Initial render
    updateSortHelpAndSummary();
}

// Export functions for use in main.js
window.initReportGeneration = initReportGeneration;
window.cancelReportGeneration = cancelReportGeneration;
window.resetProgressOverlay = resetProgressOverlay;
window.startAsyncReportGeneration = startAsyncReportGeneration;
window.startProgressPolling = startProgressPolling;
window.updateProgress = updateProgress;
window.showError = showError;
window.showDownloadButton = showDownloadButton;
window.stopProgressPolling = stopProgressPolling;