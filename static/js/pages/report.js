// Report Generation Functionality

// Global variables for progress tracking
window.currentTaskId = null;
window.progressInterval = null;
window.currentDownloadUrl = '/api/download_report/';
window.currentCancelUrl = '/api/cancel_report/';
window.currentCheckUrl = '/api/report_progress/';
// Keep polling under the 60/min endpoint limiter.
var PROGRESS_POLL_INTERVAL_MS = 1500;
var TARGET_PROGRESS_DURATION_MS = 20000;
var MAX_ACTIVE_PROGRESS_PERCENT = 95;
var PROGRESS_ANIMATION_INTERVAL_MS = 120;

function resetProgressOverlay(title) {
    if (title) {
        $('#overlayTitle').text(title);
    } else {
        $('#overlayTitle').text('Generating Report');
    }
    stopProgressAnimation();
    window.progressAnimationStartedAt = null;
    window.currentTaskStatus = 'starting';
    window.shouldShowProgressCounters = false;
    setProgressBarValue(0);
    $('#reportProgressBar').removeClass('progress-bar-striped progress-bar-animated');
    $('#progressText').text('Starting...');
    $('#entriesProcessed').text('0');
    $('#totalEntries').text('0');
    $('#progressCounters').hide();
    $('#downloadSection').hide();
    $('#errorSection').hide();
    $('#progressControls').show();
}

function setProgressBarValue(value) {
    var normalizedValue = Math.max(0, Math.min(100, Math.round(value || 0)));
    window.currentProgressBarValue = normalizedValue;
    $('#reportProgressBar').css('width', normalizedValue + '%').attr('aria-valuenow', normalizedValue);
}

function getTimedProgressPercent() {
    if (!window.progressAnimationStartedAt) {
        return 0;
    }

    var elapsed = Date.now() - window.progressAnimationStartedAt;
    var normalizedElapsed = Math.min(elapsed / TARGET_PROGRESS_DURATION_MS, 1);
    var easedProgress = 1 - Math.pow(1 - normalizedElapsed, 3);

    return MAX_ACTIVE_PROGRESS_PERCENT * easedProgress;
}

function getActiveProgressText(progressPercent) {
    if ((window.currentTaskStatus || 'starting') === 'starting' && progressPercent < 10) {
        return 'Starting...';
    }

    return 'Generating file... ' + progressPercent + '%';
}

function renderTimedProgress() {
    if ((window.currentTaskStatus || 'processing') === 'completed' || (window.currentTaskStatus || 'processing') === 'error') {
        return;
    }

    var targetProgress = getTimedProgressPercent();
    var nextProgress = Math.max(window.currentProgressBarValue || 0, targetProgress);

    setProgressBarValue(nextProgress);
    $('#progressText').text(getActiveProgressText(window.currentProgressBarValue));
}

function startProgressAnimation() {
    if (!window.progressAnimationStartedAt) {
        window.progressAnimationStartedAt = Date.now();
    }

    stopProgressAnimation();
    $('#reportProgressBar').addClass('progress-bar-striped progress-bar-animated');
    window.progressAnimationInterval = setInterval(renderTimedProgress, PROGRESS_ANIMATION_INTERVAL_MS);
    renderTimedProgress();
}

function stopProgressAnimation() {
    if (window.progressAnimationInterval) {
        clearInterval(window.progressAnimationInterval);
        window.progressAnimationInterval = null;
    }
}

function updateProgressCounters(processed, total) {
    $('#entriesProcessed').text(processed.toLocaleString());
    $('#totalEntries').text(total.toLocaleString());

    if (window.shouldShowProgressCounters && total > 0) {
        $('#progressCounters').show();
    } else {
        $('#progressCounters').hide();
    }
}

function startAsyncTask(options) {
    var config = options || {};
    if (!config.generateUrl) {
        showError('Task endpoint is not configured.');
        return;
    }

    window.currentCheckUrl = config.checkUrl || '/api/report_progress/';
    window.currentDownloadUrl = config.downloadUrl || '/api/download_report/';
    window.currentCancelUrl = config.cancelUrl || '/api/cancel_report/';
    var params = config.params;
    if (!params || typeof params !== 'object' || Array.isArray(params)) {
        params = {};
    }

    // Defensive fallback: never send an empty report payload.
    if (config.generateUrl === '/api/generate_report_async' && Object.keys(params).length === 0) {
        var hasReportForm = !!document.getElementById('reportForm');
        var hasStatsSummaryButton = !!document.getElementById('downloadStatsSummaryBtn');
        if (hasReportForm) {
            params = buildReportRequestParams();
        } else if (hasStatsSummaryButton) {
            params = { report_type: 'summary', format: 'pdf' };
        }
    }
    
    window.shouldShowProgressCounters = config.showCounters;
    if (typeof window.shouldShowProgressCounters !== 'boolean') {
        window.shouldShowProgressCounters = config.generateUrl === '/api/generate_report_async' && params.report_type !== 'summary';
    }
    
    $.ajax({
        url: config.generateUrl,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(params),
        timeout: 10000,
        success: function(response) {
            if (response.task_id) {
                window.currentTaskId = response.task_id;
                window.currentTaskStatus = 'starting';
                startProgressAnimation();
                startProgressPolling();
            } else {
                showError('Failed to start task');
            }
        },
        error: function(xhr) {
            var error = 'Unknown error';
            if (xhr.status === 429) {
                error = 'Rate limit exceeded. Please wait a while before requesting another report.';
            } else if (window.SharedUtils && typeof window.SharedUtils.buildErrorMessage === 'function') {
                error = window.SharedUtils.buildErrorMessage(xhr, error, 'bulk');
            } else if (xhr && xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON.message)) {
                error = xhr.responseJSON.error || xhr.responseJSON.message;
            }
            showError('Error starting task: ' + error);
        }
    });
}

function startAsyncReportGeneration(params) {
    startAsyncTask({
        generateUrl: '/api/generate_report_async',
        params: params,
    });
}

function buildReportRequestParams() {
    var category = $('input[name="reportCategory"]:checked').val() || 'distance';
    var limitMode = $('input[name="limitMode"]:checked').val() || 'all';
    var selectedSort = $('#sortOrderModal').val() || (category === 'distance' ? 'distance_desc' : 'operator_asc');
    var selectedFormat = $('#reportFormatModal').val() || 'pdf';

    var params = {
        limit: (limitMode === 'all') ? 'all' : ($('#reportLimitModal').val() || '50'),
        sort: selectedSort,
        report_type: category,
        format: selectedFormat
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
        if (sources.length === 0) { sources = ['atlas', 'osm']; }
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

    return params;
}

function startProgressPolling() {
    if (window.progressInterval) {
        clearInterval(window.progressInterval);
        window.progressInterval = null;
    }
    
    window.progressInterval = setInterval(function() {
        if (!window.currentTaskId) return;
        $.ajax({
            url: window.currentCheckUrl + window.currentTaskId,
            method: 'GET',
            dataType: 'json',
            cache: false,
            timeout: 8000,
            success: function(progress) {
                updateProgress(progress);
            },
            error: function(xhr) {
                // Continue polling unless specifically cancelled.
                if (window.currentTaskId) {
                    if (xhr && xhr.status === 429) {
                        console.log('Progress polling rate-limited; retrying...');
                    } else {
                        console.log('Progress polling error, continuing...');
                    }
                }
            }
        });
    }, PROGRESS_POLL_INTERVAL_MS);
}

function updateProgress(progress) {
    if (!progress) return;
    
    var processed = progress.processed || 0;
    var total = progress.total || 0;
    var status = progress.status || 'processing';

    window.currentTaskStatus = status;
    updateProgressCounters(processed, total);
    
    if (status === 'starting') {
        $('#progressText').text('Starting...');
        if (!window.progressAnimationInterval) {
            startProgressAnimation();
        }
    } else if (status === 'processing' || status === 'finalizing') {
        if (!window.progressAnimationInterval) {
            startProgressAnimation();
        }
        renderTimedProgress();
    } else if (status === 'completed') {
        stopProgressAnimation();
        $('#progressText').text('Complete!');
        setProgressBarValue(100);
        $('#reportProgressBar').removeClass('progress-bar-striped progress-bar-animated');
        stopProgressPolling();
        showDownloadButton();
    } else if (status === 'error') {
        stopProgressAnimation();
        stopProgressPolling();
        showError(progress.error || 'Unknown error occurred');
    }
}

function showDownloadButton() {
    $('#progressControls').hide();
    $('#downloadSection').show();
    
    if (window.currentTaskId) {
        // Automatically trigger the download
        setTimeout(function() {
            downloadCompletedTask(window.currentDownloadUrl + window.currentTaskId);
        }, 500);
    }
}

function getDownloadFilename(response) {
    var disposition = response.headers.get('content-disposition') || '';
    var utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
        return decodeURIComponent(utf8Match[1]);
    }

    var asciiMatch = disposition.match(/filename="?([^";]+)"?/i);
    if (asciiMatch && asciiMatch[1]) {
        return asciiMatch[1];
    }

    return null;
}

function triggerBrowserDownload(blob, filename) {
    var downloadName = filename || 'download';
    var objectUrl = window.URL.createObjectURL(blob);
    var link = document.createElement('a');

    link.href = objectUrl;
    link.download = downloadName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    window.setTimeout(function() {
        window.URL.revokeObjectURL(objectUrl);
    }, 1000);
}

function extractDownloadError(response, bodyText) {
    var message = 'Download failed.';
    var contentType = response.headers.get('content-type') || '';

    if (contentType.indexOf('application/json') !== -1) {
        try {
            var payload = JSON.parse(bodyText);
            if (payload && (payload.error || payload.message)) {
                return payload.error || payload.message;
            }
        } catch (e) {
            // Fall back to plain text handling below.
        }
    }

    if (bodyText) {
        return bodyText;
    }

    if (response.status) {
        message = 'Download failed (' + response.status + ').';
    }

    return message;
}

function downloadCompletedTask(downloadUrl) {
    $('#progressText').text('Preparing download...');

    fetch(downloadUrl, {
        method: 'GET',
        credentials: 'same-origin'
    })
        .then(function(response) {
            if (!response.ok) {
                return response.text().then(function(bodyText) {
                    throw new Error(extractDownloadError(response, bodyText));
                });
            }

            var filename = getDownloadFilename(response);
            return response.blob().then(function(blob) {
                return { blob: blob, filename: filename };
            });
        })
        .then(function(result) {
            triggerBrowserDownload(result.blob, result.filename);
            setTimeout(function() {
                $('#reportLoadingOverlay').hide();
            }, 500);
        })
        .catch(function(error) {
            showError(error && error.message ? error.message : 'Download failed.');
        });
}

function showError(message) {
    if (typeof message !== 'string') {
        message = 'An error occurred during report generation.';
    }
    stopProgressAnimation();
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
            url: window.currentCancelUrl + window.currentTaskId,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({}),
            timeout: 5000,
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
    stopProgressAnimation();
    
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
        
        var params = buildReportRequestParams();

        // Start async report generation
        startAsyncReportGeneration(params);
        
        // Hide the modal
        try {
            var reportModalEl = document.getElementById('reportModal');
            if (reportModalEl && window.bootstrap && window.bootstrap.Modal) {
                var modalInstance = window.bootstrap.Modal.getInstance(reportModalEl) || new window.bootstrap.Modal(reportModalEl);
                modalInstance.hide();
            }
        } catch (e) {}
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
        var sort = $('#sortOrderModal').val() || '';
        var mode = $('input[name="limitMode"]:checked').val();
        var limit = $('#reportLimitModal').val();
        var $limitLabel = $('#limitModeLabelUpto');
        var $sortHelp = $('#sortHelp');
        var $summary = $('#selectionSummary');

        if (!cat || !sort) return; // Prevent crashes if elements don't exist

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

    function updateFormatConstraints() {
        var format = $('#reportFormatModal').val();
        var $limitInput = $('#reportLimitModal');
        var $limitHelp = $('#limitHelpText');
        var $pdfWarning = $('#pdfLimitWarning');
        
        if (format === 'pdf') {
            $limitInput.attr('max', 2000);
            if ($limitHelp.length) $limitHelp.text('entries (max 2,000)');
            if ($pdfWarning.length) $pdfWarning.show();
            
            var currentVal = parseInt($limitInput.val(), 10);
            if (currentVal > 2000) {
                $limitInput.val(2000);
            }
        } else {
            $limitInput.attr('max', 10000);
            if ($limitHelp.length) $limitHelp.text('entries (max 10,000)');
            if ($pdfWarning.length) $pdfWarning.hide();
        }
    }

    // React on sort, limit, category changes
    $(document).on('change', '#sortOrderModal, #reportLimitModal, input[name="reportCategory"]', updateSortHelpAndSummary);
    $(document).on('change', '#reportFormatModal', updateFormatConstraints);
    
    // Initial render
    updateFormatConstraints();
    updateSortHelpAndSummary();
}

// Export functions for use in main.js
window.initReportGeneration = initReportGeneration;
window.cancelReportGeneration = cancelReportGeneration;
window.resetProgressOverlay = resetProgressOverlay;
window.startAsyncReportGeneration = startAsyncReportGeneration;
window.startAsyncTask = startAsyncTask;
window.startProgressPolling = startProgressPolling;
window.updateProgress = updateProgress;
window.showError = showError;
window.showDownloadButton = showDownloadButton;
window.stopProgressPolling = stopProgressPolling;

$(document).ready(function() {
    $('#cancelReportBtn').on('click', function() {
        cancelReportGeneration();
    });
});