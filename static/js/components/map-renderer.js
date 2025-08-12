// static/js/map-renderer.js

// This file contains shared functions for rendering markers, popups, and lines on a Leaflet map.

// Cache for reusing identical L.divIcon instances
const DivIconCache = new Map();
function getCachedDivIcon(key, html, className, size, anchor) {
    if (DivIconCache.has(key)) {
        return DivIconCache.get(key);
    }
    const icon = L.divIcon({
        html: html,
        className: className,
        iconSize: size,
        iconAnchor: anchor
    });
    DivIconCache.set(key, icon);
    return icon;
}

/**
 * MarkerClusterManager handles overlapping markers by grouping them by coordinates
 * and applying professional offset patterns with visual indicators.
 */
class MarkerClusterManager {
    constructor() {
        this.clusters = new Map(); // Key: "lat,lon", Value: array of marker data
        this.offsetRadius = 0.6; // Pixels to offset markers (12/20 for much closer positioning)
        this.coordinateTolerance = 0.00001; // Consider coordinates "same" if within this tolerance
    }

    /**
     * Creates an ATLAS marker for clustered/offset rendering.
     * Delegates to the globally available createAtlasMarker helper.
     */
    _createAtlasMarkerWithCluster(lat, lon, color, duplicateSloid, clusterSize, index, originalLat, originalLon) {
        try {
            return createAtlasMarker(lat, lon, color, duplicateSloid);
        } catch (e) {
            // Fallback to a simple circle marker if helper is unavailable
            return L.circleMarker([lat, lon], {
                color: color,
                radius: 6,
                fillOpacity: 0.5,
                weight: 2
            });
        }
    }

    /**
     * Creates an OSM marker for clustered/offset rendering.
     * Delegates to the globally available createOsmMarker helper.
     */
    _createOsmMarkerWithCluster(lat, lon, color, osmNodeType, clusterSize, index, originalLat, originalLon) {
        try {
            return createOsmMarker(lat, lon, color, osmNodeType);
        } catch (e) {
            // Fallback to a simple circle marker if helper is unavailable
            return L.circleMarker([lat, lon], {
                color: color,
                radius: 6,
                fillOpacity: 0.5,
                weight: 2
            });
        }
    }

    /**
     * Normalizes coordinates to group nearby markers together
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @returns {string} Normalized coordinate key
     */
    _normalizeCoordinates(lat, lon) {
        const normalizedLat = Math.round(lat / this.coordinateTolerance) * this.coordinateTolerance;
        const normalizedLon = Math.round(lon / this.coordinateTolerance) * this.coordinateTolerance;
        return `${normalizedLat},${normalizedLon}`;
    }

    /**
     * Adds a marker to the cluster management system
     * @param {number} lat - Latitude
     * @param {number} lon - Longitude
     * @param {Object} markerData - Marker data including type, color, popup, etc.
     */
    addMarker(lat, lon, markerData) {
        const key = this._normalizeCoordinates(lat, lon);
        
        if (!this.clusters.has(key)) {
            this.clusters.set(key, []);
        }
        
        this.clusters.get(key).push({
            lat: lat,
            lon: lon,
            ...markerData
        });
    }

    /**
     * Calculates offset positions for overlapping markers in a circular pattern
     * @param {number} centerLat - Center latitude
     * @param {number} centerLon - Center longitude
     * @param {number} count - Number of markers to offset
     * @param {number} index - Index of current marker
     * @returns {Object} Object with offsetLat and offsetLon
     */
    _calculateOffset(centerLat, centerLon, count, index) {
        if (count === 1) {
            return { offsetLat: centerLat, offsetLon: centerLon };
        }

        // Convert offset radius from pixels to approximate degrees
        // This is a rough approximation - exact conversion depends on zoom level
        const pixelToDegree = 0.000008; // Approximate conversion factor
        const radiusInDegrees = this.offsetRadius * pixelToDegree;
        
        // Arrange markers in a circular pattern around the center
        const angle = (2 * Math.PI * index) / count;
        const offsetLat = centerLat + radiusInDegrees * Math.sin(angle);
        const offsetLon = centerLon + radiusInDegrees * Math.cos(angle);
        
        return { offsetLat, offsetLon };
    }

    /**
     * Creates all markers with proper offset handling
     * @param {L.LayerGroup} layer - Leaflet layer group to add markers to
     * @returns {Array} Array of created markers
     */
     createMarkersWithOffsets(layer, options = {}) {
        const allMarkers = [];
        
        this.clusters.forEach((markerDataArray, coordKey) => {
            const [centerLat, centerLon] = coordKey.split(',').map(Number);
            const clusterSize = markerDataArray.length;
            
            // Sort markers to ensure consistent ordering (Atlas first, then OSM)
            markerDataArray.sort((a, b) => {
                if (a.type === 'atlas' && b.type === 'osm') return -1;
                if (a.type === 'osm' && b.type === 'atlas') return 1;
                return 0;
            });
            
            markerDataArray.forEach((markerData, index) => {
                const { offsetLat, offsetLon } = this._calculateOffset(centerLat, centerLon, clusterSize, index);
                
                // Create the marker with offset position
                let marker;
                if (markerData.type === 'atlas') {
                    marker = this._createAtlasMarkerWithCluster(
                        offsetLat, offsetLon, markerData.color, markerData.duplicateSloid, 
                        clusterSize, index, markerData.originalLat, markerData.originalLon
                    );
                } else {
                    marker = this._createOsmMarkerWithCluster(
                        offsetLat, offsetLon, markerData.color, markerData.osmNodeType, 
                        clusterSize, index, markerData.originalLat, markerData.originalLon
                    );
                }
                
                // Bind popup or lazy loader and add to layer
                if (markerData.popup) {
                    marker.bindPopup(markerData.popup);
                } else if (markerData.stopData && markerData.type) {
                    // Lazy-load popup on first click (no temporary placeholder)
                    marker.on('click', () => {
                        if (marker._popupLoaded || marker._popupLoading) {
                            if (marker._popupLoaded && marker.getPopup()) marker.openPopup();
                            return;
                        }
                        marker._popupLoading = true;
                        if (typeof $ !== 'undefined' && $.getJSON) {
                            $.getJSON('/api/stop_popup', { stop_id: markerData.stopData.id, view_type: markerData.type })
                              .done(function(resp) {
                                  try {
                                      const enriched = resp && (resp.stop || resp);
                                      let content = '';
                                      if (enriched && enriched.stop_type === 'unmatched') {
                                          content = markerData.type === 'atlas'
                                            ? PopupRenderer.generateSingleAtlasBubbleHtml(enriched, true)
                                            : PopupRenderer.generateSingleOsmBubbleHtml(enriched, true);
                                      } else {
                                          content = PopupRenderer.generatePopupHtml(enriched, markerData.type);
                                      }
                                      const popup = createPopupWithOptions(content);
                                      marker.bindPopup(popup);
                                      marker._popupLoaded = true;
                                      marker.openPopup();
                                  } catch (e) {
                                      console.error('Failed to render popup:', e);
                                  } finally {
                                      marker._popupLoading = false;
                                  }
                              })
                              .fail(function() {
                                  marker._popupLoading = false;
                              });
                        } else {
                            marker._popupLoading = false;
                        }
                    });
                }
                
                if (!options.deferAdd) {
                    layer.addLayer(marker);
                }
                allMarkers.push(marker);
            });
        });
        
        return allMarkers;
    }
}

/**
 * Creates a marker for an ATLAS stop.
 * @param {number} lat - Latitude.
 * @param {number} lon - Longitude.
 * @param {string} color - Marker color.
 * @param {string|null} duplicateSloid - The SLOID of a duplicate, if one exists.
 * @returns {L.Marker} A Leaflet marker.
 */
function createAtlasMarker(lat, lon, color, duplicateSloid) {
    const radius = 6;
    const size = radius * 2;
    const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 18;
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], { 
            color: color, 
            radius: radius,
            fillOpacity: 0.5,
            weight: 2
        });
    }
    if (duplicateSloid && duplicateSloid !== '') { // Check if duplicateSloid has a value
        const key = `atlas|${color}|D|${size}`;
        const icon = getCachedDivIcon(
            key,
            `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">D</text>
            </svg>`,
            'custom-div-icon',
            [size, size],
            [radius, radius]
        );
        return L.marker([lat, lon], { icon });
    } else {
        return L.circleMarker([lat, lon], { 
            color: color, 
            radius: radius,
            fillOpacity: 0.5,
            weight: 2
        });
    }
}

/**
 * Creates a marker for an OSM stop.
 * @param {number} lat - Latitude.
 * @param {number} lon - Longitude.
 * @param {string} color - Marker color.
 * @param {string} osmNodeType - The OSM node type ('platform', 'railway_station', etc.).
 * @returns {L.Marker} A Leaflet marker.
 */
function createOsmMarker(lat, lon, color, osmNodeType = null) {
    const radius = 6;
    const size = radius * 2;
    const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 18;
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], { 
            color: color, 
            radius: radius,
            fillOpacity: 0.5,
            weight: 2
        });
    }
    
    if (osmNodeType === 'platform') {
        const key = `osm|${color}|P|${size}`;
        const icon = getCachedDivIcon(
            key,
            `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">P</text>
            </svg>`,
            'custom-div-icon',
            [size, size],
            [radius, radius]
        );
        return L.marker([lat, lon], { icon });
    } else if (osmNodeType === 'railway_station') {
        const key = `osm|${color}|S|${size}`;
        const icon = getCachedDivIcon(
            key,
            `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">S</text>
            </svg>`,
            'custom-div-icon',
            [size, size],
            [radius, radius]
        );
        return L.marker([lat, lon], { icon });
    } else {
        return L.circleMarker([lat, lon], { 
            color: color, 
            radius: radius,
            fillOpacity: 0.5,
            weight: 2
        });
    }
}

/**
 * Enhanced marker creation function that handles overlapping markers
 * @param {Array} markerDataArray - Array of marker data objects
 * @param {L.LayerGroup} layer - Leaflet layer group to add markers to
 * @returns {Array} Array of created markers
 */
function addLayersInChunks(layer, markers, batchSize = 200) {
    let currentIndex = 0;
    function addNextChunk() {
        const end = Math.min(currentIndex + batchSize, markers.length);
        for (let i = currentIndex; i < end; i++) {
            try { layer.addLayer(markers[i]); } catch (e) {}
        }
        currentIndex = end;
        if (currentIndex < markers.length) {
            setTimeout(addNextChunk, 0);
        }
    }
    addNextChunk();
}

function createMarkersWithOverlapHandling(markerDataArray, layer, options = {}) {
    const clusterManager = new MarkerClusterManager();
    
    // Add all markers to the cluster manager
    markerDataArray.forEach(markerData => {
        clusterManager.addMarker(markerData.lat, markerData.lon, markerData);
    });
    
    // Create markers with offset handling, deferring actual add if batching
    const markers = clusterManager.createMarkersWithOffsets(layer, { deferAdd: !!options.batchAdd });
    if (options.batchAdd) {
        const batchSize = options.batchSize || 200;
        addLayersInChunks(layer, markers, batchSize);
    }
    return markers;
}

// Popup-related functions have been moved to popup-renderer.js
// Use PopupRenderer.* functions instead of global functions

/**
 * A wrapper for L.popup to apply consistent options.
 * @param {string} content - HTML content for the popup.
 * @returns {L.Popup} A Leaflet popup instance.
 */
function createPopupWithOptions(content) {
    // move_popup.js provides L.draggablePopup
    if (L.draggablePopup) {
        return L.draggablePopup({
            autoClose: false,
            closeOnClick: false,
            autoPan: false,
            maxWidth: 300,
            closeButton: true,
            className: 'customPopup permanent-popup'
        }).setContent(content);
    }
    // Fallback to standard popup if draggable isn't loaded
    return L.popup({
        autoClose: false,
        closeOnClick: false,
        autoPan: false,
        maxWidth: 300,
        closeButton: true,
        className: 'customPopup permanent-popup'
    }).setContent(content);
}

/**
 * Attach standard popup line handling (open/close/move/zoom) to a Leaflet map.
 * Returns a live array reference of currently open popups for optional callers.
 * This mirrors the behavior used on the main map.
 * @param {L.Map} mapInstance
 * @returns {Array<L.Popup>} openPopups
 */
function attachPopupLineHandlersToMap(mapInstance) {
    const openPopups = [];
    mapInstance.on('popupopen', function(e) {
        openPopups.push(e.popup);
        try {
            // Always work with the actual popup DOM element
            const contentEl = e.popup.getElement();
            if (!contentEl) return;
            const $root = $(contentEl);
            const $container = $root.find('.popup-content-container').first();
            const stopId = $container.data('stop-id');
            const type = $container.data('type'); // 'atlas' or 'osm'
            if (!(stopId && type)) return;

            const $btn = $root.find('button.manual-match-target');

            // Ensure UI reflects current selection state
            if (typeof window.updateManualMatchButtonsUI === 'function') {
                window.updateManualMatchButtonsUI();
            }

            $btn.off('click.mm').on('click.mm', function(){
                const current = window.manualMatchContext;
                if (!current) {
                    // Start selection from this popup
                    window.manualMatchContext = { from: type, stopId: stopId };
                    $('.manual-match-banner').remove();
                    const msg = type === 'atlas' ? 'Select an OSM entry to complete the match' : 'Select an ATLAS entry to complete the match';
                    const banner = $(`
                        <div class="manual-match-banner alert alert-info" role="alert" style="position:fixed; top:10px; left:50%; transform:translateX(-50%); z-index:2000;">
                            ${msg}
                            <button type="button" class="btn btn-sm btn-outline-secondary ml-2" id="cancelManualMatch">Cancel</button>
                        </div>
                    `);
                    $('body').append(banner);
                    $('#cancelManualMatch').on('click', function(){
                        window.manualMatchContext = null;
                        $('.manual-match-banner').remove();
                        if (typeof window.updateManualMatchButtonsUI === 'function') {
                            window.updateManualMatchButtonsUI();
                        }
                    });
                    if (typeof window.updateManualMatchButtonsUI === 'function') {
                        window.updateManualMatchButtonsUI();
                    }
                    return;
                }

                // Attempt to finalize if clicking on opposite dataset
                if ((current.from === 'atlas' && type === 'osm') || (current.from === 'osm' && type === 'atlas')) {
                    const atlasId = current.from === 'atlas' ? current.stopId : stopId;
                    const osmId   = current.from === 'atlas' ? stopId : current.stopId;
                    const makePersistent = (typeof ProblemsState !== 'undefined' && ProblemsState.getAutoPersistEnabled && ProblemsState.getAutoPersistEnabled()) || false;

                    $.ajax({
                        url: '/api/manual_match',
                        method: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify({ atlas_stop_id: atlasId, osm_stop_id: osmId, make_persistent: makePersistent }),
                    }).done(function(resp){
                        window.manualMatchContext = null;
                        $('.manual-match-banner').remove();
                        // Success notification
                        if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                            window.ProblemsUI.showTemporaryMessage('Manual match saved' + (resp && resp.is_persistent ? ' (persistent)' : ''), 'success');
                        }
                        // Optional: refresh Problems view if present
                        if (typeof ProblemsData !== 'undefined' && ProblemsData.fetchProblems && typeof ProblemsState !== 'undefined') {
                            const idx = ProblemsState.getCurrentProblemIndex ? ProblemsState.getCurrentProblemIndex() : 0;
                            ProblemsData.fetchProblems(ProblemsState.getCurrentPage ? ProblemsState.getCurrentPage() : 1);
                            setTimeout(() => {
                                if (window.ProblemsUI && window.ProblemsUI.displayProblem) {
                                    window.ProblemsUI.displayProblem(idx);
                                }
                            }, 400);
                        }
                        if (typeof window.updateManualMatchButtonsUI === 'function') {
                            window.updateManualMatchButtonsUI();
                        }
                    }).fail(function(){
                        if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                            window.ProblemsUI.showTemporaryMessage('Failed to save manual match', 'error');
                        }
                    });
                }
            });
        } catch (err) { /* ignore */ }
    });
    mapInstance.on('popupclose', function(e) {
        const idx = openPopups.indexOf(e.popup);
        if (idx !== -1) openPopups.splice(idx, 1);
        if (e.popup instanceof L.DraggablePopup && e.popup._line) {
            try { e.popup._removeLine(); } catch {}
        }
    });
    mapInstance.on('move', function() {
        if (window.updateAllPopupLines) window.updateAllPopupLines();
        openPopups.forEach(popup => { if (popup._updatePosition) popup._updatePosition(); });
    });
    mapInstance.on('zoom', function() {
        if (window.updateAllPopupLines) window.updateAllPopupLines();
        openPopups.forEach(popup => { if (popup._updatePosition) popup._updatePosition(); });
    });
    return openPopups;
}

// Global helper to keep popup buttons in sync with current manual selection
window.updateManualMatchButtonsUI = function() {
    const ctx = window.manualMatchContext;
    // For every visible popup, set appropriate button text
    $('.leaflet-popup').each(function(){
        const $root = $(this);
        const $container = $root.find('.popup-content-container').first();
        const type = $container.data('type');
        const $btn = $root.find('button.manual-match-target');
        if (!$btn.length) return;
        if (ctx && ctx.from && ((ctx.from === 'atlas' && type === 'osm') || (ctx.from === 'osm' && type === 'atlas'))) {
            $btn.text('Match to this entry');
        } else {
            $btn.text('Match to');
        }
    });
};

/**
 * Draws a problem case on the map, including markers and lines.
 * @param {L.Map} map - The Leaflet map instance.
 * @param {object} problemData - The data for the problem stop.
 * @param {object} layers - An object containing layer groups for markers and lines.
 */
function drawProblemOnMap(map, problemData, layers) {
    layers.markersLayer.clearLayers();
    layers.linesLayer.clearLayers();

    const stop = problemData;
    let popup;

    // Case: 'distance' or 'attributes' problem (a matched pair)
    if ((stop.problem === 'distance' || stop.problem === 'attributes') && stop.stop_type === 'matched' && stop.atlas_lat && stop.osm_lat) {
        const atlasMarker = createAtlasMarker(stop.atlas_lat, stop.atlas_lon, 'green', stop.atlas_duplicate_sloid);
        const atlasPopup = createPopupWithOptions(PopupRenderer.generatePopupHtml(stop, 'atlas'));
        atlasMarker.bindPopup(atlasPopup).addTo(layers.markersLayer);
        
        const osmMarker = createOsmMarker(stop.osm_lat, stop.osm_lon, 'blue', stop.osm_node_type);
        const osmPopup = createPopupWithOptions(PopupRenderer.generatePopupHtml(stop, 'osm'));
        osmMarker.bindPopup(osmPopup).addTo(layers.markersLayer);
        
        // Use same line styling as main page for consistency
        const line = L.polyline([[stop.atlas_lat, stop.atlas_lon], [stop.osm_lat, stop.osm_lon]], { 
            color: 'green', 
            weight: 2
        });
        line.addTo(layers.linesLayer);

        map.fitBounds(line.getBounds().pad(0.2));
        atlasMarker.openPopup();
    }
    // Case: 'unmatched' problem
    else if (stop.problem === 'unmatched') {
        if (stop.stop_type === 'unmatched' && stop.atlas_lat) { // Isolated ATLAS
            const marker = createAtlasMarker(stop.atlas_lat, stop.atlas_lon, 'red', stop.atlas_duplicate_sloid);
            popup = createPopupWithOptions(PopupRenderer.generateSingleAtlasBubbleHtml(stop, true));
            marker.bindPopup(popup).addTo(layers.markersLayer);
            map.setView([stop.atlas_lat, stop.atlas_lon], 16);
            marker.openPopup();
        } else if (stop.stop_type === 'osm' && stop.osm_lat) { // Isolated OSM
            const marker = createOsmMarker(stop.osm_lat, stop.osm_lon, 'gray', stop.osm_node_type);
            popup = createPopupWithOptions(PopupRenderer.generateSingleOsmBubbleHtml(stop, true));
            marker.bindPopup(popup).addTo(layers.markersLayer);
            map.setView([stop.osm_lat, stop.osm_lon], 16);
            marker.openPopup();
        }
    }
    // Case: 'duplicates' group
    else if (stop.problem === 'duplicates') {
        const members = Array.isArray(stop.members) ? stop.members : [];
        const points = [];
        members.forEach(member => {
            if (member.atlas_lat != null && member.atlas_lon != null) {
                const m = createAtlasMarker(member.atlas_lat, member.atlas_lon, 'orange', member.atlas_duplicate_sloid);
                const p = createPopupWithOptions(PopupRenderer.generatePopupHtml(member, 'atlas'));
                m.bindPopup(p).addTo(layers.markersLayer);
                points.push([member.atlas_lat, member.atlas_lon]);
            }
            if (member.osm_lat != null && member.osm_lon != null) {
                const m2 = createOsmMarker(member.osm_lat, member.osm_lon, 'blue', member.osm_node_type);
                const p2 = createPopupWithOptions(PopupRenderer.generatePopupHtml(member, 'osm'));
                m2.bindPopup(p2).addTo(layers.markersLayer);
                points.push([member.osm_lat, member.osm_lon]);
            }
        });
        if (points.length > 0) {
            const bounds = L.latLngBounds(points);
            map.fitBounds(bounds.pad(0.2));
        }
    }
}


