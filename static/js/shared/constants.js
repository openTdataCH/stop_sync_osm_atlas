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

        // OSM group/trio connector lines are deferred to a higher zoom for performance
        ZOOM_OSM_GROUP_LINE_THRESHOLD: 17,

        // At or above this zoom level, markers may switch to labeled DOM icons (D/P/S)
        LABEL_ICON_MIN_ZOOM: 18,
        
        // Number of additional zoom levels to keep the "zoom in" banner visible
        ADDITIONAL_BANNER_ZOOM_LEVELS: 2,
        
        // Default map center (Switzerland coordinates: Zurich)
        DEFAULT_CENTER: [47.3769, 8.5417],
        
        // Default zoom level when map first loads
        DEFAULT_ZOOM: 14,
        
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
        GENERAL_LIMIT: 1800,
        
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
        MIN_WIDTH: 130,
        
        // Minimum height in pixels
        MIN_HEIGHT: 100,
        
        // Width for "auto" sizing
        INITIAL_WIDTH: 'auto',
        
        // Height for "auto" sizing
        INITIAL_HEIGHT: 'auto',
        
        // Margin in pixels for resize handle detection
        RESIZE_MARGIN: 10,
        
        // Hard max width for single bubble popups
        SINGLE_BUBBLE_MAX_WIDTH_PX: 380,
        
        // Optimal width per bubble for multi-bubble layouts
        MULTI_BUBBLE_OPTIMAL_WIDTH: 180,

        // Hard max width for multi-bubble matched popups
        MULTI_BUBBLE_MAX_WIDTH_PX: 420,

        // Max width allowed when user manually resizes popup
        MULTI_BUBBLE_RESIZE_MAX_WIDTH_PX: 900,

        // Maximum number of bubbles per row in matched view
        MULTI_BUBBLE_MAX_COLUMNS: 2,
        
        // Extra pixels buffer for bubble expansion
        BUBBLE_EXPANSION_BUFFER: 12
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
    AppConstants.COLORS = Object.freeze({
        // Brand anchors
        NAVY_PRIMARY: '#174092',
        NAVY_PRIMARY_HOVER: '#123D90',

        // Map semantics
        ATLAS_MATCHED: '#174092',
        OSM_MATCHED: '#4CAF50',
        ATLAS_UNMATCHED: '#DC3545',
        OSM_UNMATCHED: '#6C757D',
        LINE_ATLAS_OSM: '#174092',
        LINE_OSM_GROUP: '#4CAF50',
        LINE_OSM_GROUP_DASH: '6,4',
        LINE_OSM_GROUP_DASH_ALT: '4,4',
        TEMP_MARKER: '#174092',

        // Compatibility aliases for legacy callers
        MATCHED: '#174092',
        MATCHED_LIGHT: '#4F8FEF',
        UNMATCHED: '#DC3545',
        UNMATCHED_LIGHT: '#FF8A80',
        OSM_BLUE: '#174092',
        ATLAS_RED: '#DC3545',

        // Other semantic markers
        DUPLICATE: '#F0AD4E',
        DISTANCE_WARNING: '#F0AD4E',
        OPERATOR_MISMATCH: '#6C757D'
    });

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

