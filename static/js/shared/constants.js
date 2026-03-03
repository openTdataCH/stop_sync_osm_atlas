/**
 * Application-wide constants and configuration values
 * 
 * This file centralizes all magic numbers and configuration values
 * to make them easy to find, understand, and modify.
 */
(function(global) {
    'use strict';

    const AppConstants = {};

    // ==========================================
    // MAP CONFIGURATION
    // ==========================================
    
    /**
     * Map zoom level thresholds for rendering optimization
     */
    AppConstants.MAP = {
        // Prevent zooming out to a world/continent view (app is Switzerland-focused)
        // Leaflet zoom: ~2-3 is world/continent, ~5 is Europe, ~6-7 is central Europe.
        MIN_ZOOM: 8,

        // Below this zoom level, markers are not rendered (performance optimization)
        ZOOM_MARKER_THRESHOLD: 13,
        
        // Below this zoom level, connection lines between matches are not rendered
        ZOOM_LINE_THRESHOLD: 13,
        
        // Number of additional zoom levels to keep the "zoom in" banner visible
        ADDITIONAL_BANNER_ZOOM_LEVELS: 2,
        
        // Default map center (Switzerland coordinates: Zurich)
        DEFAULT_CENTER: [47.3769, 8.5417],
        
        // Default zoom level when map first loads
        DEFAULT_ZOOM: 13,
        
        // Maximum zoom level (allows upscaling tiles for better precision)
        MAX_ZOOM: 20,

        // Maximum zoom level where tiles are actually available
        MAX_NATIVE_ZOOM: 19,

        // Keep panning constrained to a Switzerland-centric "half of Europe" envelope.
        // Format: [[southWestLat, southWestLon], [northEastLat, northEastLon]]
        MAX_BOUNDS: [[45.5, 5.5], [48.0, 11.0]],

        // How strongly Leaflet resists panning outside MAX_BOUNDS (1.0 = hard stop)
        MAX_BOUNDS_VISCOSITY: 1.0
    };

    /**
     * Data loading and performance limits
     */
    AppConstants.DATA_LOADING = {
        // If filtered results are <= this count, render markers even below zoom threshold
        LOW_ZOOM_SMALLSET_LIMIT: 550,
        
        // Data cap for all zoom levels below the uncapped threshold
        GENERAL_LIMIT: 2000,
        
        // Debounce delay (ms) for map pan/zoom events to prevent excessive API calls
        VIEW_DEBOUNCE_MS: 150
    };

    /**
     * Context markers limits for problems page
     */
    AppConstants.CONTEXT_MARKERS = {
        // Maximum context markers to show at low zoom
        LOW_ZOOM_LIMIT: 150,
        
        // Maximum context markers to show at high zoom
        HIGH_ZOOM_LIMIT: 200
    };

    // ==========================================
    // DISTANCE & MATCHING
    // ==========================================
    
    /**
     * Distance thresholds for stop matching and filtering
     */
    AppConstants.DISTANCE = {
        // Distance in meters to consider stops "nearby"
        NEARBY_THRESHOLD_METERS: 50,
        
        // Maximum distance for distance matching algorithms
        MAX_MATCHING_DISTANCE: 500,
        
        // Default value for "Top N" distance filter
        TOP_N_DEFAULT: 10
    };

    // ==========================================
    // UI COMPONENTS
    // ==========================================
    
    /**
     * Popup window dimensions and behavior
     */
    AppConstants.POPUP = {
        // Minimum width in pixels
        MIN_WIDTH: 150,
        
        // Minimum height in pixels
        MIN_HEIGHT: 100,
        
        // Width for "auto" sizing
        INITIAL_WIDTH: 'auto',
        
        // Height for "auto" sizing
        INITIAL_HEIGHT: 'auto',
        
        // Margin in pixels for resize handle detection
        RESIZE_MARGIN: 10,
        
        // Factor for single bubble maximum width expansion
        SINGLE_BUBBLE_MAX_WIDTH_FACTOR: 1.5,
        
        // Optimal width per bubble for multi-bubble layouts
        MULTI_BUBBLE_OPTIMAL_WIDTH: 250,
        
        // Extra pixels buffer for bubble expansion
        BUBBLE_EXPANSION_BUFFER: 20
    };

    /**
     * Animation and timing constants
     */
    AppConstants.TIMING = {
        // Duration for temporary message display (ms)
        MESSAGE_DISPLAY_DURATION: 3000,
        
        // Longer duration for important messages (ms)
        MESSAGE_LONG_DURATION: 5000,
        
        // Fade in animation duration (ms)
        FADE_IN_DURATION: 200,
        
        // Fade out animation duration (ms)
        FADE_OUT_DURATION: 500,
        
        // Short delay for UI updates (ms)
        SHORT_DELAY: 50,
        
        // Debounce delay for search/filter inputs (ms)
        DEBOUNCE_DELAY: 300
    };

    /**
     * Marker clustering and rendering
     */
    AppConstants.MARKERS = {
        // Pixels to offset markers in a cluster
        CLUSTER_OFFSET_RADIUS: 0.6,
        
        // Coordinate tolerance for considering positions "same"
        COORDINATE_TOLERANCE: 0.00001,
        
        // Default marker radius
        DEFAULT_RADIUS: 6,
        
        // Marker weight (border thickness)
        DEFAULT_WEIGHT: 2,
        
        // Fill opacity for markers
        DEFAULT_FILL_OPACITY: 0.5
    };

    /**
     * Zoom banner styling (used in main.js ensureZoomBannerExists)
     */
    AppConstants.ZOOM_BANNER = {
        TOP_POSITION: '10px',
        BACKGROUND: 'rgba(0,0,0,0.75)',
        COLOR: '#fff',
        PADDING: '8px 12px',
        BORDER_RADIUS: '6px',
        FONT_SIZE: '14px',
        Z_INDEX: '1000'
    };

    // ==========================================
    // PAGINATION & DATA LIMITS
    // ==========================================
    
    /**
     * Pagination settings for data tables and lists
     */
    AppConstants.PAGINATION = {
        // Default number of items per page
        DEFAULT_PAGE_SIZE: 50,
        
        // Maximum items per page
        MAX_PAGE_SIZE: 500,
        
        // Items per page for reports
        REPORT_PAGE_SIZE: 100
    };

    // ==========================================
    // COLORS & STYLING
    // ==========================================
    
    /**
     * Standard colors used throughout the application
     */
    AppConstants.COLORS = {
        // Matched stops
        MATCHED: '#4CAF50',
        MATCHED_LIGHT: '#81C784',
        
        // Unmatched stops
        UNMATCHED: '#FF5252',
        UNMATCHED_LIGHT: '#FF8A80',
        
        // OSM-specific
        OSM_BLUE: '#3388ff',
        
        // ATLAS-specific
        ATLAS_RED: '#e74c3c',
        
        // Duplicate stops
        DUPLICATE: '#FF9800',
        
        // Distance issues
        DISTANCE_WARNING: '#FFC107',
        
        // Operator mismatch
        OPERATOR_MISMATCH: '#9C27B0'
    };

    // ==========================================
    // API & NETWORKING
    // ==========================================
    
    /**
     * API request configuration
     */
    AppConstants.API = {
        // Request timeout in milliseconds
        REQUEST_TIMEOUT: 30000,
        
        // Maximum retry attempts
        MAX_RETRIES: 3,
        
        // Delay between retries (ms)
        RETRY_DELAY: 1000
    };

    // Export to global scope
    global.AppConstants = AppConstants;

})(window);

