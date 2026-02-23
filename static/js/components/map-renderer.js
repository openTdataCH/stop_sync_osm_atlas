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

// Robust truthiness helper for duplicate flags coming from mixed backends
// Treats null/undefined/empty/"false"/"0"/"none"/"null" as false; anything else as true
function isDuplicateFlagSet(value) {
    return !!value;
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
                        if (typeof $ !== 'undefined' && $.getJSON) {
                            $.getJSON('/api/stop_popup', { stop_id: markerData.stopData.id, view_type: markerData.type })
                                .done(function (resp) {
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
                                })
                                .fail(function () {
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
 * @param {boolean} hasAtlasDuplicate - Whether this stop has an atlas duplicate.
 * @returns {L.Marker} A Leaflet marker.
 */
function createAtlasMarker(lat, lon, color, hasAtlasDuplicate) {
    const radius = AppConstants.MARKERS.DEFAULT_RADIUS;
    const weight = AppConstants.MARKERS.DEFAULT_WEIGHT;
    const fillOpacity = AppConstants.MARKERS.DEFAULT_FILL_OPACITY;
    const size = radius * 2;
    const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 23;
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], {
            color: color,
            radius: radius,
            fillOpacity: fillOpacity,
            weight: weight
        });
    }
    if (hasAtlasDuplicate) { // Show labeled icon only when truly flagged
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
function createOsmMarker(lat, lon, color, osmNodeType = null) {
    const radius = AppConstants.MARKERS.DEFAULT_RADIUS;
    const weight = AppConstants.MARKERS.DEFAULT_WEIGHT;
    const fillOpacity = AppConstants.MARKERS.DEFAULT_FILL_OPACITY;
    const size = radius * 2;
    const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 23;
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], {
            color: color,
            radius: radius,
            fillOpacity: fillOpacity,
            weight: weight
        });
    }

    if (osmNodeType === 'platform') {
        const icon = getCachedLabeledCircleIcon('osm', color, 'P', size, radius, weight, fillOpacity);
        return L.marker([lat, lon], { icon: icon });
    } else if (osmNodeType === 'railway_station') {
        const icon = getCachedLabeledCircleIcon('osm', color, 'S', size, radius, weight, fillOpacity);
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
    // move_popup.js provides L.draggablePopup
    if (L.draggablePopup) {
        return L.draggablePopup({
            autoClose: false,
            closeOnClick: false,
            autoPan: false,
            maxWidth: 2000,
            closeButton: true,
            className: 'customPopup permanent-popup'
        }).setContent(content);
    }
    // Fallback to standard popup if draggable isn't loaded
    return L.popup({
        autoClose: false,
        closeOnClick: false,
        autoPan: false,
        maxWidth: 2000,
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

            // Load popup notes content when the collapsible is present
            const $notes = $root.find('.popup-notes');
            if ($notes.length) {
                $notes.each(function () {
                    const $el = $(this);
                    const type = $el.data('type');
                    const sloid = $el.data('sloid');
                    const osmNodeId = $el.data('osm-node-id');
                    const params = type === 'atlas' ? { sloid: sloid } : { osm_node_id: osmNodeId };
                    $.getJSON('/api/notes', params, function (resp) {
                        const your = resp && resp.your ? resp.your : null;
                        const others = resp && Array.isArray(resp.others) ? resp.others : [];
                        const yourVal = (your && your.note) ? your.note : '';
                        const isPersistent = !!(your && your.is_persistent);
                        const idPrefix = type === 'atlas' ? 'popupAtlas' : 'popupOsm';
                        const editorHtml = `
                            <div class="popup-note-editor">
                                <textarea class="form-control form-control-sm mb-1" id="${idPrefix}Note" placeholder="Add a note..."></textarea>
                                <div class="d-flex align-items-center">
                                    <button class="btn btn-sm btn-primary mr-2 save-popup-note" data-type="${type}">${'Save note'}</button>
                                    <label class="form-check form-check-inline align-middle ml-1 mb-0 small">
                                        <input class="form-check-input popup-note-persist" type="checkbox" ${isPersistent ? 'checked' : ''}> <span class="form-check-label"> Make persistent</span>
                                    </label>
                                </div>
                                <div class="small text-muted mt-2">Other user notes</div>
                                <div class="popup-others-notes"></div>
                            </div>`;
                        $el.html(editorHtml);
                        $el.find(`#${idPrefix}Note`).val(yourVal);
                        const othersHtml = others.length ? others.map(o => {
                            const ts = o.updated_at ? new Date(o.updated_at).toLocaleString() : '';
                            return `<div class="card card-body py-1 px-2 mb-1"><div class="small"><strong>${o.author_email || 'Unknown user'}</strong> · <span class="text-muted">${ts}</span></div><div>${SharedUtils.escapeHtml(o.note || '')}</div></div>`;
                        }).join('') : '<div class="text-muted small"><em>No other persistent notes.</em></div>';
                        $el.find('.popup-others-notes').html(othersHtml);
                    });
                });

                // Delegate save handler inside popup
                $root.off('click.savePopupNote').on('click.savePopupNote', '.save-popup-note', function () {
                    const $editor = $(this).closest('.popup-note-editor');
                    const isAtlas = $(this).data('type') === 'atlas';
                    const note = $editor.find('textarea').val();
                    const makePersistent = $editor.find('.popup-note-persist').is(':checked');
                    const payload = { note: note, make_persistent: makePersistent };
                    if (isAtlas) payload.sloid = $notes.data('sloid'); else payload.osm_node_id = $notes.data('osm-node-id');
                    const url = isAtlas ? '/api/save_note/atlas' : '/api/save_note/osm';
                    const btn = $(this);
                    const original = btn.html();
                    btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');
                    $.ajax({ url: url, method: 'POST', contentType: 'application/json', data: JSON.stringify(payload) })
                        .done(function (resp) {
                            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                                window.ProblemsUI.showTemporaryMessage('Note saved' + (resp && resp.is_persistent ? ' (persistent)' : ''), 'success');
                            }
                        })
                        .fail(function (xhr) {
                            if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                                window.ProblemsUI.showTemporaryMessage('Error saving note', 'error');
                            }
                        })
                        .always(function () { btn.prop('disabled', false).html(original); });
                });
            }

            // Ensure UI reflects current selection state
            if (typeof window.updateManualMatchButtonsUI === 'function') {
                window.updateManualMatchButtonsUI();
            }

            $btn.off('click.mm').on('click.mm', function () {
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
                    $('#cancelManualMatch').on('click', function () {
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
                    const osmId = current.from === 'atlas' ? stopId : current.stopId;
                    const makePersistent = (typeof ProblemsState !== 'undefined' && ProblemsState.getAutoPersistEnabled && ProblemsState.getAutoPersistEnabled()) || false;

                    $.ajax({
                        url: '/api/manual_match',
                        method: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify({ atlas_stop_id: atlasId, osm_stop_id: osmId, make_persistent: makePersistent }),
                    }).done(function (resp) {
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
                    }).fail(function () {
                        if (window.ProblemsUI && window.ProblemsUI.showTemporaryMessage) {
                            window.ProblemsUI.showTemporaryMessage('Failed to save manual match', 'error');
                        }
                    });
                }
            });
        } catch (err) { /* ignore */ }
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

// Global helper to keep popup buttons in sync with current manual selection
window.updateManualMatchButtonsUI = function () {
    const ctx = window.manualMatchContext;
    // For every visible popup, set appropriate button text
    $('.leaflet-popup').each(function () {
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
        const atlasMarker = createAtlasMarker(stop.atlas_lat, stop.atlas_lon, 'green', stop.has_atlas_duplicate);
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
        if (stop.stop_type === 'atlas_unmatched' && stop.atlas_lat) { // Isolated ATLAS
            const marker = createAtlasMarker(stop.atlas_lat, stop.atlas_lon, 'red', stop.has_atlas_duplicate);
            popup = createPopupWithOptions(PopupRenderer.generateSingleAtlasBubbleHtml(stop, true));
            marker.bindPopup(popup).addTo(layers.markersLayer);
            map.setView([stop.atlas_lat, stop.atlas_lon], 16);
            marker.openPopup();
        } else if (stop.stop_type === 'osm_unmatched' && stop.osm_lat) { // Isolated OSM
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
        const markerDataArray = [];
        // Only render popups for the duplicated side when group_type is provided
        const isOsmGroup = stop.group_type === 'osm';
        const isAtlasGroup = stop.group_type === 'atlas';
        members.forEach(member => {
            // Show ATLAS side only if not an OSM-duplicates group
            if (!isOsmGroup && member.atlas_lat != null && member.atlas_lon != null) {
                // Use same color semantics as main map: green matched, red unmatched, orange stations
                let atlasColor = 'green';
                if (member.stop_type === 'atlas_unmatched') {
                    atlasColor = 'red';
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
                    popup: createPopupWithOptions(PopupRenderer.generatePopupHtml(member, 'atlas'))
                });
                points.push([member.atlas_lat, member.atlas_lon]);
            }
            // Show OSM side only if not an ATLAS-duplicates group
            if (!isAtlasGroup && member.osm_lat != null && member.osm_lon != null) {
                markerDataArray.push({
                    lat: parseFloat(member.osm_lat),
                    lon: parseFloat(member.osm_lon),
                    type: 'osm',
                    color: 'blue',
                    osmNodeType: member.osm_node_type,
                    originalLat: parseFloat(member.osm_lat),
                    originalLon: parseFloat(member.osm_lon),
                    stopData: member,
                    popup: createPopupWithOptions(PopupRenderer.generatePopupHtml(member, 'osm'))
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


