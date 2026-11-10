// The Data page's export form. The progress overlay is export-progress.js.

function reportFieldValue(selector) {
    var field = document.querySelector(selector);
    return field ? field.value : undefined;
}

function isReportBoxChecked(id) {
    var box = document.getElementById(id);
    return !!(box && box.checked);
}

function buildReportRequestParams() {
    var category = reportFieldValue('input[name="reportCategory"]:checked') || 'distance';
    var limitMode = reportFieldValue('input[name="limitMode"]:checked') || 'all';
    var selectedSort = reportFieldValue('#sortOrderModal') || (category === 'distance' ? 'distance_desc' : 'operator_asc');
    var selectedFormat = reportFieldValue('#reportFormatModal') || 'pdf';

    var params = {
        limit: (limitMode === 'all') ? 'all' : (reportFieldValue('#reportLimitModal') || '50'),
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
    if (isReportBoxChecked('includeAtlasCoords')) includeFields.push('atlas_coords');
    if (isReportBoxChecked('includeOsmCoords')) includeFields.push('osm_coords');
    if (includeFields.length > 0) params.include_fields = includeFields.join(',');

    if (category === 'unmatched') {
        var sources = [];
        if (isReportBoxChecked('sourceAtlas')) sources.push('atlas');
        if (isReportBoxChecked('sourceOsm')) sources.push('osm');
        if (sources.length === 0) { sources = ['atlas', 'osm']; }
        params.sources = sources.join(',');
    } else if (category === 'problems') {
        // Problem types
        var ptypes = [
            ['ptypeDistance', 'distance'],
            ['ptypeUnmatched', 'unmatched'],
            ['ptypeAttributes', 'attributes'],
            ['ptypeContradictsRouteMatching', 'contradicts_route_matching'],
            ['ptypeDuplicates', 'duplicates'],
            ['ptypeDisused', 'disused'],
            ['ptypeIdentifier', 'identifier']
        ].filter(function (entry) { return isReportBoxChecked(entry[0]); }).map(function (entry) { return entry[1]; });
        if (ptypes.length > 0) params.problem_types = ptypes.join(',');

        // Priorities
        var pris = ['1', '2', '3'].filter(function (priority) { return isReportBoxChecked('priority' + priority); });
        if (pris.length > 0) params.priorities = pris.join(',');
    }

    return params;
}

// Starts a Data page export in the progress overlay.
function startReportExport(params, title) {
    ExportProgress.open(title);
    ExportProgress.start({
        generateUrl: '/api/generate_report_async',
        params: params,
        showCounters: params.report_type !== 'summary'
    });
}

// Function to initialize report generation features
function initReportGeneration() {
    var form = document.getElementById('reportForm');
    if (!form) return;

    window.operatorDropdownReports = new OperatorDropdown('#atlasOperatorFilterReports', {
        placeholder: 'Select operators...',
        multiple: true
    });

    var sortSelect = document.getElementById('sortOrderModal');
    var limitInput = document.getElementById('reportLimitModal');

    function setShown(id, shown) {
        var element = document.getElementById(id);
        if (element) element.style.display = shown ? '' : 'none';
    }

    function setText(id, text) {
        var element = document.getElementById(id);
        if (element) element.textContent = text;
    }

    // Toggle sections based on category selection
    function updateCategoryVisibility() {
        var cat = reportFieldValue('input[name="reportCategory"]:checked');
        document.getElementById('unmatchedOptions').hidden = cat !== 'unmatched';
        document.getElementById('problemsOptions').hidden = cat !== 'problems';
        // Constrain sort options by category: distance sorts only for matched
        // pairs, priority sorts only for problems.
        Array.from(sortSelect.options).forEach(function (option) {
            var hidden = (option.value.indexOf('priority_') === 0 && cat !== 'problems')
                || (option.value.indexOf('distance_') === 0 && cat !== 'distance');
            option.disabled = hidden;
            option.style.display = hidden ? 'none' : '';
        });
        // If current value is disabled, reset to a valid default
        var selected = sortSelect.options[sortSelect.selectedIndex];
        if (selected && selected.disabled) {
            sortSelect.value = cat === 'distance' ? 'distance_desc' : cat === 'problems' ? 'priority_desc' : 'operator_asc';
        }
    }

    // Update helper text and summary reflecting the current selection
    function updateSortHelpAndSummary() {
        var cat = reportFieldValue('input[name="reportCategory"]:checked');
        var sort = sortSelect.value || '';
        var mode = reportFieldValue('input[name="limitMode"]:checked');
        var limit = limitInput.value;

        if (!cat || !sort) return;

        // Label: "Top" when sorting by distance/priority desc, else "First"
        var isTop = (sort === 'distance_desc') || (sort === 'priority_desc');
        setText('limitModeLabelUpto', isTop ? 'Top' : 'First');

        var categoryName = { distance: 'Matched pairs', unmatched: 'Unmatched entries', problems: 'Problems' }[cat] || '';
        var sortName = '';
        if (sort.indexOf('operator_') === 0) sortName = 'operator';
        if (sort.indexOf('distance_') === 0) sortName = 'distance';
        if (sort.indexOf('priority_') === 0) sortName = 'priority';
        var direction = sort.endsWith('_asc') ? 'ascending' : 'descending';

        var summary = categoryName + ' sorted by ' + sortName + ' (' + direction + ')';
        if (mode === 'upto') {
            summary += ', ' + (isTop ? 'top' : 'first') + ' ' + (limit || 'N') + ' entries';
        }
        setText('selectionSummary', summary);
    }

    function updateFormatConstraints() {
        var isPdf = reportFieldValue('#reportFormatModal') === 'pdf';
        var max = isPdf ? 2000 : 10000;
        limitInput.setAttribute('max', max);
        setText('limitHelpText', 'entries (max ' + max.toLocaleString('en-US') + ')');
        setShown('pdfLimitWarning', isPdf);
        if (isPdf && parseInt(limitInput.value, 10) > max) limitInput.value = max;
    }

    form.addEventListener('change', function (event) {
        var target = event.target;
        if (target.name === 'reportCategory') updateCategoryVisibility();
        if (target.name === 'limitMode') {
            limitInput.disabled = reportFieldValue('input[name="limitMode"]:checked') !== 'upto';
        }
        if (target.id === 'reportFormatModal') updateFormatConstraints();
        updateSortHelpAndSummary();
    });

    // Handle the report form submission
    form.addEventListener('submit', function (event) {
        event.preventDefault();
        startReportExport(buildReportRequestParams());
    });

    updateCategoryVisibility();
    updateFormatConstraints();
    updateSortHelpAndSummary();
}

window.initReportGeneration = initReportGeneration;
window.buildReportRequestParams = buildReportRequestParams;
window.startReportExport = startReportExport;
