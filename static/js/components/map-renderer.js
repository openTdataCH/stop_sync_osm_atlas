// static/js/map-renderer.js

// This file contains shared functions for rendering markers, popups, and lines on a Leaflet map.

// Cache for reusing identical L.divIcon instances
const DivIconCache = new Map();
const MAP_RENDERER_LABEL_ICON_MIN_ZOOM = (typeof AppConstants !== 'undefined' && AppConstants.MAP && AppConstants.MAP.LABEL_ICON_MIN_ZOOM) || 18;
const MAP_RENDERER_COLORS = (typeof AppConstants !== 'undefined' && AppConstants.COLORS) || {};
const COLOR_ATLAS_MATCHED = MAP_RENDERER_COLORS.ATLAS_MATCHED || '#174092';
const COLOR_OSM_MATCHED = MAP_RENDERER_COLORS.OSM_MATCHED || '#4CAF50';
const COLOR_ATLAS_UNMATCHED = MAP_RENDERER_COLORS.ATLAS_UNMATCHED || '#DC3545';
const COLOR_OSM_UNMATCHED = MAP_RENDERER_COLORS.OSM_UNMATCHED || '#6C757D';
const COLOR_LINE_ATLAS_OSM = MAP_RENDERER_COLORS.LINE_ATLAS_OSM || '#174092';
const OSM_LABEL_BY_NODE_TYPE = Object.freeze({
    platform: 'P',
    railway_station: 'S'
});

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

// Robust truthiness helper for duplicate flags coming from mixed backends
// Treats null/undefined/empty/"false"/"0"/"none"/"null" as false; anything else as true
function isDuplicateFlagSet(value) {
    if (value === true) return true;
    if (value === false || value == null) return false;
    if (typeof value === 'number') return value !== 0 && !Number.isNaN(value);
    if (typeof value === 'string') {
        const normalized = value.trim().toLowerCase();
        return !(normalized === '' || normalized === 'false' || normalized === '0' || normalized === 'none' || normalized === 'null' || normalized === 'undefined');
    }
    return !!value;
}

function resolveMarkerZoom(zoomOverride) {
    if (typeof zoomOverride === 'number' && !Number.isNaN(zoomOverride)) {
        return zoomOverride;
    }
    if (typeof map !== 'undefined' && map && map.getZoom) {
        return map.getZoom();
    }
    return MAP_RENDERER_LABEL_ICON_MIN_ZOOM;
}

function shouldUseCanvasMarker(zoomOverride) {
    return resolveMarkerZoom(zoomOverride) < MAP_RENDERER_LABEL_ICON_MIN_ZOOM;
}

function resolveOsmLabel(osmNodeType) {
    return OSM_LABEL_BY_NODE_TYPE[osmNodeType] || null;
}

// Helper to build and cache a labeled circle SVG icon
function getCachedLabeledCircleIcon(keyPrefix, color, letter, size, radius, weight, fillOpacity) {
    const key = `${keyPrefix}|${color}|${letter}|${size}`;
    const html = `\n            <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">\n                <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="${fillOpacity}" stroke="${color}" stroke-width="${weight}"/>\n                <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">${letter}</text>\n            </svg>`;
    return getCachedDivIcon(key, html, 'custom-div-icon', [size, size], [radius, radius]);
}

/**
 * MarkerClusterManager handles overlapping markers by grouping them by coordinates
 * and applying professional offset patterns with visual indicators.
 */
class MarkerClusterManager {
    constructor() {
        this.clusters = new Map(); // Key: "lat,lon", Value: array of marker data
        this.offsetRadius = AppConstants.MARKERS.CLUSTER_OFFSET_RADIUS; // Pixels to offset markers
        this.coordinateTolerance = AppConstants.MARKERS.COORDINATE_TOLERANCE; // Consider coordinates "same" if within this tolerance
    }

    /**
     * Creates an ATLAS marker for clustered/offset rendering.
     * Delegates to the globally available createAtlasMarker helper.
     */
    _createAtlasMarkerWithCluster(lat, lon, color, hasAtlasDuplicate, clusterSize, index, originalLat, originalLon) {
        try {
            return createAtlasMarker(lat, lon, color, hasAtlasDuplicate);
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
     * Returns the clustered data with calculated offsets, without creating Leaflet markers.
     * @returns {Array} Array of objects { lat, lon, markerData }
     */
    getClusteredData() {
        const results = [];
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
                results.push({
                    lat: offsetLat,
                    lon: offsetLon,
                    markerData: markerData
                });
            });
        });
        return results;
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
                        offsetLat, offsetLon, markerData.color, markerData.hasAtlasDuplicate,
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
                        $.ajax({
                            url: '/api/stop_popup',
                            method: 'GET',
                            dataType: 'json',
                            data: { stop_id: markerData.stopData.id, view_type: markerData.type },
                            cache: false,
                            timeout: 8000,
                            success: function (resp) {
                                try {
                                    const enriched = resp && (resp.stop || resp);
                                    let content = '';
                                    if (enriched && enriched.stop_type === 'atlas_unmatched') {
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
                            },
                            error: function () {
                                marker._popupLoading = false;
                            }
                        });
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
 * @param {boolean} hasAtlasDuplicate - Whether this stop has an atlas duplicate.
 * @returns {L.Marker} A Leaflet marker.
 */
function createAtlasMarker(lat, lon, color, hasAtlasDuplicate, zoomOverride) {
    const radius = AppConstants.MARKERS.DEFAULT_RADIUS;
    const weight = AppConstants.MARKERS.DEFAULT_WEIGHT;
    const fillOpacity = AppConstants.MARKERS.DEFAULT_FILL_OPACITY;
    const size = radius * 2;
    const useCanvasOnly = shouldUseCanvasMarker(zoomOverride);
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], {
            color: color,
            radius: radius,
            fillOpacity: fillOpacity,
            weight: weight
        });
    }
    if (isDuplicateFlagSet(hasAtlasDuplicate)) { // Show labeled icon only when truly flagged
        const icon = getCachedLabeledCircleIcon('atlas', color, 'D', size, radius, weight, fillOpacity);
        return L.marker([lat, lon], { icon: icon });
    } else {
        return L.circleMarker([lat, lon], {
            color: color,
            radius: radius,
            fillOpacity: fillOpacity,
            weight: weight
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
function createOsmMarker(lat, lon, color, osmNodeType = null, zoomOverride) {
    const radius = AppConstants.MARKERS.DEFAULT_RADIUS;
    const weight = AppConstants.MARKERS.DEFAULT_WEIGHT;
    const fillOpacity = AppConstants.MARKERS.DEFAULT_FILL_OPACITY;
    const size = radius * 2;
    const useCanvasOnly = shouldUseCanvasMarker(zoomOverride);
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], {
            color: color,
            radius: radius,
            fillOpacity: fillOpacity,
            weight: weight
        });
    }

    const label = resolveOsmLabel(osmNodeType);
    if (label) {
        const icon = getCachedLabeledCircleIcon('osm', color, label, size, radius, weight, fillOpacity);
        return L.marker([lat, lon], { icon: icon });
    } else {
        return L.circleMarker([lat, lon], {
            color: color,
            radius: radius,
            fillOpacity: fillOpacity,
            weight: weight
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
            try { layer.addLayer(markers[i]); } catch (e) { }
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
    const defaultMaxWidth = (AppConstants.POPUP && AppConstants.POPUP.MULTI_BUBBLE_RESIZE_MAX_WIDTH_PX)
        ? AppConstants.POPUP.MULTI_BUBBLE_RESIZE_MAX_WIDTH_PX
        : 900;

    // move_popup.js provides L.draggablePopup
    if (L.draggablePopup) {
        return L.draggablePopup({
            autoClose: false,
            closeOnClick: false,
            autoPan: false,
            maxWidth: defaultMaxWidth,
            closeButton: true,
            className: 'customPopup permanent-popup'
        }).setContent(content);
    }
    // Fallback to standard popup if draggable isn't loaded
    return L.popup({
        autoClose: false,
        closeOnClick: false,
        autoPan: false,
        maxWidth: defaultMaxWidth,
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
    mapInstance.on('popupopen', function (e) {
        openPopups.push(e.popup);
    });
    mapInstance.on('popupclose', function (e) {
        const idx = openPopups.indexOf(e.popup);
        if (idx !== -1) openPopups.splice(idx, 1);
        if (e.popup instanceof L.DraggablePopup && e.popup._line) {
            try { e.popup._removeLine(); } catch { }
        }
    });
    mapInstance.on('move', function () {
        if (window.updateAllPopupLines) window.updateAllPopupLines();
        openPopups.forEach(popup => { if (popup._updatePosition) popup._updatePosition(); });
    });
    mapInstance.on('zoom', function () {
        if (window.updateAllPopupLines) window.updateAllPopupLines();
        openPopups.forEach(popup => { if (popup._updatePosition) popup._updatePosition(); });
    });
    return openPopups;
}

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
    const popupRenderer = window.PopupRenderer;
    if (!popupRenderer) {
        console.error('PopupRenderer is not defined. Check popup-renderer.js load/parse errors.');
        return;
    }
    let popup;

    // Case: 'distance' or 'attributes' problem (a matched pair)
    if ((stop.problem === 'distance' || stop.problem === 'attributes') && stop.stop_type === 'matched' && stop.atlas_lat && stop.osm_lat) {
        const atlasMarker = createAtlasMarker(stop.atlas_lat, stop.atlas_lon, COLOR_ATLAS_MATCHED, stop.has_atlas_duplicate);
        const atlasPopup = createPopupWithOptions(popupRenderer.generatePopupHtml(stop, 'atlas'));
        atlasMarker.bindPopup(atlasPopup).addTo(layers.markersLayer);

        const osmMarker = createOsmMarker(stop.osm_lat, stop.osm_lon, COLOR_OSM_MATCHED, stop.osm_node_type);
        const osmPopup = createPopupWithOptions(popupRenderer.generatePopupHtml(stop, 'osm'));
        osmMarker.bindPopup(osmPopup).addTo(layers.markersLayer);

        // Use same line styling as main page for consistency
        const line = L.polyline([[stop.atlas_lat, stop.atlas_lon], [stop.osm_lat, stop.osm_lon]], {
            color: COLOR_LINE_ATLAS_OSM,
            weight: 2
        });
        line.addTo(layers.linesLayer);

        map.fitBounds(line.getBounds().pad(0.2));
        atlasMarker.openPopup();
    }
    // Case: 'unmatched' problem
    else if (stop.problem === 'unmatched') {
        if (stop.stop_type === 'atlas_unmatched' && stop.atlas_lat) { // Isolated ATLAS
            const marker = createAtlasMarker(stop.atlas_lat, stop.atlas_lon, COLOR_ATLAS_UNMATCHED, stop.has_atlas_duplicate);
            popup = createPopupWithOptions(popupRenderer.generateSingleAtlasBubbleHtml(stop, true));
            marker.bindPopup(popup).addTo(layers.markersLayer);
            map.setView([stop.atlas_lat, stop.atlas_lon], 16);
            marker.openPopup();
        } else if (stop.stop_type === 'osm_unmatched' && stop.osm_lat) { // Isolated OSM
            const marker = createOsmMarker(stop.osm_lat, stop.osm_lon, COLOR_OSM_UNMATCHED, stop.osm_node_type);
            popup = createPopupWithOptions(popupRenderer.generateSingleOsmBubbleHtml(stop, true));
            marker.bindPopup(popup).addTo(layers.markersLayer);
            map.setView([stop.osm_lat, stop.osm_lon], 16);
            marker.openPopup();
        }
    }
    // Case: 'duplicates' group
    else if (stop.problem === 'duplicates') {
        const members = Array.isArray(stop.members) ? stop.members : [];
        const points = [];
        const markerDataArray = [];
        // Only render popups for the duplicated side when group_type is provided
        const isOsmGroup = stop.group_type === 'osm';
        const isAtlasGroup = stop.group_type === 'atlas';
        members.forEach(member => {
            // Show ATLAS side only if not an OSM-duplicates group
            if (!isOsmGroup && member.atlas_lat != null && member.atlas_lon != null) {
                let atlasColor = COLOR_ATLAS_MATCHED;
                if (member.stop_type === 'atlas_unmatched') {
                    atlasColor = COLOR_ATLAS_UNMATCHED;
                }
                markerDataArray.push({
                    lat: parseFloat(member.atlas_lat),
                    lon: parseFloat(member.atlas_lon),
                    type: 'atlas',
                    color: atlasColor,
                    hasAtlasDuplicate: member.has_atlas_duplicate,
                    originalLat: parseFloat(member.atlas_lat),
                    originalLon: parseFloat(member.atlas_lon),
                    stopData: member,
                    popup: createPopupWithOptions(popupRenderer.generatePopupHtml(member, 'atlas'))
                });
                points.push([member.atlas_lat, member.atlas_lon]);
            }
            // Show OSM side only if not an ATLAS-duplicates group
            if (!isAtlasGroup && member.osm_lat != null && member.osm_lon != null) {
                markerDataArray.push({
                    lat: parseFloat(member.osm_lat),
                    lon: parseFloat(member.osm_lon),
                    type: 'osm',
                    color: COLOR_OSM_MATCHED,
                    osmNodeType: member.osm_node_type,
                    originalLat: parseFloat(member.osm_lat),
                    originalLon: parseFloat(member.osm_lon),
                    stopData: member,
                    popup: createPopupWithOptions(popupRenderer.generatePopupHtml(member, 'osm'))
                });
                points.push([member.osm_lat, member.osm_lon]);
            }
        });
        const createdMarkers = createMarkersWithOverlapHandling(markerDataArray, layers.markersLayer);
        if (points.length > 0) {
            const bounds = L.latLngBounds(points);
            map.fitBounds(bounds.pad(0.2));
        }
        // Open a limited number of popups to avoid clutter
        createdMarkers.slice(0, 6).forEach(m => { try { m.openPopup(); } catch (e) { } });
    }
}