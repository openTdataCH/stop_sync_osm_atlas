// static/js/map-renderer.js

// This file contains shared functions for rendering markers, popups, and lines on a Leaflet map.

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
    createMarkersWithOffsets(layer) {
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
                
                // Bind popup and add to layer
                if (markerData.popup) {
                    marker.bindPopup(markerData.popup);
                }
                
                layer.addLayer(marker);
                allMarkers.push(marker);
            });
        });
        
        return allMarkers;
    }

    /**
     * Creates an Atlas marker with cluster visual indicators
     */
    _createAtlasMarkerWithCluster(lat, lon, color, duplicateSloid, clusterSize, index, originalLat, originalLon) {
        const radius = 6;
        const size = radius * 2;
        const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 14;

        // Prefer canvas at lower zooms to reduce DOM load
        if (useCanvasOnly) {
            return L.circleMarker([lat, lon], { 
                color: color, 
                radius: radius,
                fillOpacity: 0.5,
                weight: 2
            });
        }

        if (duplicateSloid && duplicateSloid !== '') {
            return L.marker([lat, lon], {
                icon: L.divIcon({
                    html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                            <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                            <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">D</text>
                        </svg>`,
                    className: 'custom-div-icon atlas-marker-cluster',
                    iconSize: [size, size],
                    iconAnchor: [radius, radius]
                })
            });
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
     * Creates an OSM marker with cluster visual indicators
     */
    _createOsmMarkerWithCluster(lat, lon, color, osmNodeType, clusterSize, index, originalLat, originalLon) {
        const radius = 6;
        const size = radius * 2;
        const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 14;

        // Prefer canvas at lower zooms to reduce DOM load
        if (useCanvasOnly) {
            return L.circleMarker([lat, lon], { 
                color: color, 
                radius: radius,
                fillOpacity: 0.5,
                weight: 2
            });
        }

        if (osmNodeType === 'platform') {
            return L.marker([lat, lon], {
                icon: L.divIcon({
                    html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                            <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                            <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">P</text>
                        </svg>`,
                    className: 'custom-div-icon osm-marker-cluster',
                    iconSize: [size, size],
                    iconAnchor: [radius, radius]
                })
            });
        } else if (osmNodeType === 'railway_station') {
            return L.marker([lat, lon], {
                icon: L.divIcon({
                    html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                            <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                            <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">S</text>
                        </svg>`,
                    className: 'custom-div-icon osm-marker-cluster',
                    iconSize: [size, size],
                    iconAnchor: [radius, radius]
                })
            });
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
     * Generates a subtle cluster indicator for multiple markers
     */
    _generateClusterIndicator(clusterSize, index) {
        // Remove cluster indicator functionality - return empty string
        return '';
    }

    /**
     * Clear all clusters
     */
    clear() {
        this.clusters.clear();
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
    const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 14;
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], { 
            color: color, 
            radius: radius,
            fillOpacity: 0.5,
            weight: 2
        });
    }
    if (duplicateSloid && duplicateSloid !== '') { // Check if duplicateSloid has a value
        return L.marker([lat, lon], {
            icon: L.divIcon({
                html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                        <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                        <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">D</text>
                      </svg>`,
                className: 'custom-div-icon',
                iconSize: [size, size],
                iconAnchor: [radius, radius]
            })
        });
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
    const useCanvasOnly = (typeof map !== 'undefined') && map && map.getZoom && map.getZoom() < 14;
    if (useCanvasOnly) {
        return L.circleMarker([lat, lon], { 
            color: color, 
            radius: radius,
            fillOpacity: 0.5,
            weight: 2
        });
    }
    
    if (osmNodeType === 'platform') {
        return L.marker([lat, lon], {
            icon: L.divIcon({
                html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                        <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                        <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">P</text>
                      </svg>`,
                className: 'custom-div-icon',
                iconSize: [size, size],
                iconAnchor: [radius, radius]
            })
        });
    } else if (osmNodeType === 'railway_station') {
        return L.marker([lat, lon], {
            icon: L.divIcon({
                html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                        <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="0.5" stroke="${color}" stroke-width="2"/>
                        <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">S</text>
                      </svg>`,
                className: 'custom-div-icon',
                iconSize: [size, size],
                iconAnchor: [radius, radius]
            })
        });
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
function createMarkersWithOverlapHandling(markerDataArray, layer) {
    const clusterManager = new MarkerClusterManager();
    
    // Add all markers to the cluster manager
    markerDataArray.forEach(markerData => {
        clusterManager.addMarker(markerData.lat, markerData.lon, markerData);
    });
    
    // Create markers with offset handling
    return clusterManager.createMarkersWithOffsets(layer);
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
    // Case: 'isolated' problem
    else if (stop.problem === 'isolated') {
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
} 