// Report Generation Functionality

// Function to initialize report generation features
function initReportGeneration() {
    // Update the generate report button to show the modal instead
    $('#generateReportBtn').on('click', function(){
        $('#reportModal').modal('show');
    });
    
    // Handle the report form submission
    $('#reportForm').on('submit', function(e){
        e.preventDefault();
        
        // Get values from the modal
        var params = {
            limit: $('#reportLimitModal').val(),
            sort: $('#sortOrderModal').val(),
            report_type: $('#reportTypeModal').val(),
            format: $('#reportFormatModal').val()
        };

        // Generate the report URL with parameters
        var url = "/api/generate_report?" + $.param(params);
        window.location.href = url;
        
        // Hide the modal
        $('#reportModal').modal('hide');
    });
}

// Export functions for use in main.js
window.initReportGeneration = initReportGeneration; 