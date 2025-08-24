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

    // Handle the report form submission
    $('#reportForm').on('submit', function(e){
        e.preventDefault();
        
        // Show loading overlay
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

        // Generate the report URL with parameters
        var url = "/api/generate_report?" + $.param(params);
        
        // Start download and hide overlay after a short delay
        window.location.href = url;
        
        // Hide overlay after 2 seconds (giving time for download to start)
        setTimeout(function() {
            $('#reportLoadingOverlay').hide();
        }, 2000);
        
        // Hide the modal
        try { $('#reportModal').modal('hide'); } catch (e) {}
    });

    // Enable/disable limit input based on mode
    $(document).on('change', 'input[name="limitMode"]', function() {
        var mode = $('input[name="limitMode"]:checked').val();
        if (mode === 'upto') { $('#reportLimitModal').prop('disabled', false); }
        else { $('#reportLimitModal').prop('disabled', true); }
    });
}

// Function to cancel report generation
function cancelReportGeneration() {
    $('#reportLoadingOverlay').hide();
}

// Export functions for use in main.js
window.initReportGeneration = initReportGeneration;
window.cancelReportGeneration = cancelReportGeneration; 