/**
 * LineRenderer - Centralized module for drawing connection lines between matched ATLAS-OSM pairs
 * 
 * This module consolidates all line drawing logic to:
 * - Ensure consistent behavior across all match types (1:1, 1:N, N:1)
 * - Prevent duplicate lines with a tracking Set
 * - Apply consistent styling based on match type
 * - Handle zoom thresholds in one place
 * 
 * @module LineRenderer
 */
(function(global) {
    'use strict';

    const LineRenderer = {};

    // ==========================================
    // LINE STYLE CONFIGURATION
    // ==========================================
    
    /**
     * Style definitions for different match types
     * @constant {Object}
     */
    const LINE_STYLES = {
        // Standard automatic match (exact, name, distance, route matching)
        default: { 
            color: 'green', 
            weight: 2,
            opacity: 1
        },
        // Manual match that has been persisted to the database
        manualPersistent: { 
            color: 'purple', 
            weight: 2,
            opacity: 1
        },
        // Manual match that is temporary (not yet persisted)
        manualTemporary: { 
            color: 'purple', 
            weight: 2, 
            dashArray: '5,5',
            opacity: 1
        },
        // Context/background lines (used in problems view)
        context: {
            color: 'green',
            weight: 2,
            opacity: 0.4
        },
        // Context manual match lines
        contextManual: {
            color: 'purple',
            weight: 2,
            opacity: 0.6
        },
        // Context manual temporary lines
        contextManualTemporary: {
            color: 'purple',
            weight: 2,
            opacity: 0.6,
            dashArray: '5,5'
        }
    };

    // ==========================================
    // PUBLIC API
    // ==========================================

    /**
     * Get the appropriate line style for a match
     * 
     * @param {string} matchType - The type of match ('exact', 'name', 'manual', 'distance_matching_*', etc.)
     * @param {boolean} isPersistent - Whether a manual match is persisted
     * @param {boolean} isContext - Whether this is a context/background line
     * @returns {Object} Leaflet polyline style options
     */
    LineRenderer.getStyle = function(matchType, isPersistent, isContext) {
        if (isContext) {
            if (matchType === 'manual') {
                return isPersistent ? LINE_STYLES.contextManual : LINE_STYLES.contextManualTemporary;
            }
            return LINE_STYLES.context;
        }
        
        if (matchType === 'manual') {
            return isPersistent ? LINE_STYLES.manualPersistent : LINE_STYLES.manualTemporary;
        }
        
        return LINE_STYLES.default;
    };

    /**
     * Draw all connection lines for the given stops data.
     * This is the main entry point for line drawing on the main map.
     * 
     * @param {Array} data - Array of stop objects from the API
     * @param {L.LayerGroup} layer - Leaflet layer group to add lines to
     * @param {Object} options - Configuration options
     * @param {boolean} options.showAtlas - Whether ATLAS nodes are visible
     * @param {boolean} options.showOsm - Whether OSM nodes are visible
     * @param {number} options.minZoom - Minimum zoom level to draw lines
     * @param {number} options.currentZoom - Current map zoom level
     * @param {boolean} [options.isContext=false] - Whether these are context/background lines
     * @returns {number} Number of lines drawn
     */
    LineRenderer.drawAll = function(data, layer, options) {
        const { showAtlas, showOsm, minZoom, currentZoom, isContext } = options;
        
        // Early exit conditions
        if (currentZoom < minZoom) {
            return 0;
        }
        
        if (!showAtlas || !showOsm) {
            return 0;
        }
        
        if (!Array.isArray(data) || data.length === 0) {
            return 0;
        }
        
        // Track drawn lines to prevent duplicates
        // Key format: "sloid-osm_node_id"
        const drawnKeys = new Set();
        let lineCount = 0;
        
        data.forEach(function(stop) {
            if (stop.stop_type !== 'matched') {
                return;
            }
            
            const linesDrawn = LineRenderer._drawLinesForStop(stop, layer, drawnKeys, isContext);
            lineCount += linesDrawn;
        });
        
        return lineCount;
    };

    /**
     * Draw a single line between two coordinates.
     * Useful for drawing lines outside the main data iteration.
     * 
     * @param {L.LayerGroup} layer - Leaflet layer group to add the line to
     * @param {number} atlasLat - ATLAS latitude
     * @param {number} atlasLon - ATLAS longitude
     * @param {number} osmLat - OSM latitude
     * @param {number} osmLon - OSM longitude
     * @param {Object} [styleOptions] - Optional style override
     * @returns {L.Polyline} The created polyline
     */
    LineRenderer.drawLine = function(layer, atlasLat, atlasLon, osmLat, osmLon, styleOptions) {
        const style = styleOptions || LINE_STYLES.default;
        const line = L.polyline([
            [atlasLat, atlasLon],
            [osmLat, osmLon]
        ], style);
        layer.addLayer(line);
        return line;
    };

    /**
     * Clear all non-manual-match lines from a layer.
     * Preserves lines marked with isManualMatch option for overlay persistence.
     * 
     * @param {L.LayerGroup} layer - Layer to clear
     */
    LineRenderer.clearLines = function(layer) {
        if (!layer) return;
        
        layer.eachLayer(function(line) {
            // Preserve lines explicitly marked as manual match overlays
            if (!line.options || !line.options.isManualMatch) {
                layer.removeLayer(line);
            }
        });
    };

    /**
     * Clear all lines from a layer (including manual match lines).
     * 
     * @param {L.LayerGroup} layer - Layer to clear
     */
    LineRenderer.clearAllLines = function(layer) {
        if (!layer) return;
        layer.clearLayers();
    };

    // ==========================================
    // PRIVATE METHODS
    // ==========================================

    /**
     * Draw connection lines for a single stop record.
     * Handles both osm_matches array and single-match fallback.
     * 
     * @private
     * @param {Object} stop - Stop data object
     * @param {L.LayerGroup} layer - Layer to add lines to
     * @param {Set} drawnKeys - Set tracking already-drawn line keys
     * @param {boolean} isContext - Whether this is a context line
     * @returns {number} Number of lines drawn for this stop
     */
    LineRenderer._drawLinesForStop = function(stop, layer, drawnKeys, isContext) {
        // Must have valid ATLAS coordinates
        if (!stop.atlas_lat || !stop.atlas_lon) {
            return 0;
        }
        
        let linesDrawn = 0;
        
        // Determine OSM nodes to connect to
        // Priority: osm_matches array > single osm_node_id
        const osmNodes = LineRenderer._getOsmNodesFromStop(stop);
        
        osmNodes.forEach(function(osm) {
            // Validate OSM coordinates
            if (osm.osm_lat == null || osm.osm_lon == null) {
                return;
            }
            
            // Build unique key for deduplication
            const osmNodeId = osm.osm_node_id || stop.osm_node_id;
            const key = LineRenderer._buildLineKey(stop.sloid, osmNodeId);
            
            // Skip if already drawn
            if (drawnKeys.has(key)) {
                return;
            }
            drawnKeys.add(key);
            
            // Determine match type - check osm-specific match_type first, then stop-level
            const matchType = osm.match_type || stop.match_type;
            const isPersistent = osm.manual_is_persistent || stop.manual_is_persistent;
            
            // Get appropriate style
            const style = LineRenderer.getStyle(matchType, isPersistent, isContext);
            
            // Create and add the line
            const line = L.polyline([
                [parseFloat(stop.atlas_lat), parseFloat(stop.atlas_lon)],
                [parseFloat(osm.osm_lat), parseFloat(osm.osm_lon)]
            ], style);
            
            layer.addLayer(line);
            linesDrawn++;
        });
        
        return linesDrawn;
    };

    /**
     * Extract OSM nodes from a stop object.
     * Returns an array of OSM data objects to iterate over.
     * 
     * @private
     * @param {Object} stop - Stop data object
     * @returns {Array} Array of OSM node data objects
     */
    LineRenderer._getOsmNodesFromStop = function(stop) {
        // If osm_matches array exists and has entries, use it
        if (Array.isArray(stop.osm_matches) && stop.osm_matches.length > 0) {
            return stop.osm_matches;
        }
        
        // Fallback to single OSM node from stop object itself
        if (stop.osm_node_id) {
            return [{
                osm_node_id: stop.osm_node_id,
                osm_lat: stop.osm_lat,
                osm_lon: stop.osm_lon,
                match_type: stop.match_type,
                manual_is_persistent: stop.manual_is_persistent
            }];
        }
        
        // No OSM data available
        return [];
    };

    /**
     * Build a unique key for a line connection.
     * Used to prevent duplicate lines.
     * 
     * @private
     * @param {string} sloid - ATLAS SLOID
     * @param {string} osmNodeId - OSM node ID
     * @returns {string} Unique key string
     */
    LineRenderer._buildLineKey = function(sloid, osmNodeId) {
        // Handle null/undefined values gracefully
        const s = sloid || 'unknown_atlas';
        const o = osmNodeId || 'unknown_osm';
        return `${s}-${o}`;
    };

    // ==========================================
    // EXPORT MODULE
    // ==========================================
    
    global.LineRenderer = LineRenderer;

})(window);
