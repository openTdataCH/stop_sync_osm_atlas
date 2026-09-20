// Shared, domain-neutral Leaflet marker and popup primitives.

// Cache for reusing identical L.divIcon instances
const DivIconCache = new Map();
const MAP_RENDERER_LABEL_ICON_MIN_ZOOM = (typeof AppConstants !== 'undefined' && AppConstants.MAP && AppConstants.MAP.LABEL_ICON_MIN_ZOOM) || 18;
const MARKER_OVERLAP_POINT_EPSILON_PX = 0.00001;
const MIN_VISIBLE_OVERLAP_OFFSET_PX = 0.5;
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

// Helper to build and cache a labeled circle SVG icon
function getCachedLabeledCircleIcon(keyPrefix, color, letter, size, radius, weight, fillOpacity) {
    const key = `${keyPrefix}|${color}|${letter}|${size}|${weight}|${fillOpacity}`;
    const html = `\n            <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">\n                <circle cx="${radius}" cy="${radius}" r="${radius}" fill="${color}" fill-opacity="${fillOpacity}" stroke="${color}" stroke-width="${weight}"/>\n                <text x="${radius}" y="${radius + 2}" text-anchor="middle" fill="white" font-size="${radius + 2}" font-weight="bold">${letter}</text>\n            </svg>`;
    return getCachedDivIcon(key, html, 'custom-div-icon', [size, size], [radius, radius]);
}

/**
 * Groups near-coincident markers within a maximum-zoom pixel threshold and
 * gives each member a small, stable display displacement. Source coordinates
 * are never mutated; callers receive separate display coordinates.
 */
class MarkerClusterManager {
    constructor(options = {}) {
        this.map = options.map || null;
        this.zoom = typeof options.zoom === 'number' ? options.zoom : null;
        this.entries = [];
        this.offsetRadius = AppConstants.MARKERS.CLUSTER_OFFSET_RADIUS;
        this.coordinateTolerance = AppConstants.MARKERS.COORDINATE_TOLERANCE;
        this.overlapDistance = (
            typeof options.overlapDistance === 'number' && options.overlapDistance > 0
        ) ? options.overlapDistance : this.offsetRadius * 2;
        this.referenceZoom = this._resolveReferenceZoom(options.referenceZoom);
    }

    _resolveReferenceZoom(override) {
        if (typeof override === 'number' && Number.isFinite(override)) return override;
        if (this.map && typeof this.map.getMaxZoom === 'function') {
            const mapMaxZoom = this.map.getMaxZoom();
            if (typeof mapMaxZoom === 'number' && Number.isFinite(mapMaxZoom)) return mapMaxZoom;
        }
        const configuredMaxZoom = AppConstants.MAP && AppConstants.MAP.MAX_ZOOM;
        return (typeof configuredMaxZoom === 'number' && Number.isFinite(configuredMaxZoom))
            ? configuredMaxZoom
            : 20;
    }

    _hasProjection() {
        return !!(
            this.map &&
            typeof this.map.project === 'function' &&
            typeof this.map.unproject === 'function'
        );
    }

    _hasVisibleLayoutOffset() {
        if (typeof this.zoom !== 'number' || !Number.isFinite(this.zoom)) return true;
        const currentPixelRadius = this.offsetRadius * Math.pow(2, this.zoom - this.referenceZoom);
        return currentPixelRadius >= MIN_VISIBLE_OVERLAP_OFFSET_PX;
    }

    _sortEntries(entries) {
        return entries.sort((a, b) => {
            const rank = { atlas: 0, osm: 1, gtfs: 2 };
            const aType = a.entityType || '';
            const bType = b.entityType || '';
            const typeDifference = (rank[aType] ?? 9) - (rank[bType] ?? 9);
            if (typeDifference !== 0) return typeDifference;
            const aKey = String(a.key || '');
            const bKey = String(b.key || '');
            return aKey.localeCompare(bKey);
        });
    }

    /**
     * Adds a marker without changing its source coordinate.
     */
    addMarker(lat, lon, markerData) {
        const sourceLat = (lat == null || (typeof lat === 'string' && lat.trim() === ''))
            ? NaN
            : Number(lat);
        const sourceLon = (lon == null || (typeof lon === 'string' && lon.trim() === ''))
            ? NaN
            : Number(lon);
        if (!Number.isFinite(sourceLat) || !Number.isFinite(sourceLon)) return false;

        this.entries.push({
            ...markerData,
            lat: sourceLat,
            lon: sourceLon
        });
        return true;
    }

    _locateEntries() {
        const useProjection = this._hasProjection();
        const entries = this._sortEntries(this.entries.slice());
        return {
            useProjection: useProjection,
            threshold: useProjection ? this.overlapDistance : this.coordinateTolerance,
            members: entries.map((entry) => {
                const point = useProjection
                    ? this.map.project([entry.lat, entry.lon], this.referenceZoom)
                    : { x: entry.lon, y: entry.lat };
                return { entry: entry, point: { x: Number(point.x), y: Number(point.y) } };
            })
        };
    }

    /**
     * Build non-transitive proximity groups around deterministic anchors.
     * A spatial index avoids coordinate-rounding boundaries and keeps dense
     * co-located data linear rather than comparing every marker with every other.
     */
    _buildGroups() {
        const located = this._locateEntries();
        const threshold = located.threshold;
        const thresholdSquared = threshold * threshold;
        const grid = new Map();
        const groups = [];

        function cellKey(x, y) {
            return `${x}:${y}`;
        }

        located.members.forEach((member) => {
            const cellX = Math.floor(member.point.x / threshold);
            const cellY = Math.floor(member.point.y / threshold);
            let selectedGroup = null;
            let selectedDistanceSquared = Infinity;

            for (let x = cellX - 1; x <= cellX + 1; x++) {
                for (let y = cellY - 1; y <= cellY + 1; y++) {
                    const candidates = grid.get(cellKey(x, y)) || [];
                    candidates.forEach((group) => {
                        const dx = member.point.x - group.anchor.x;
                        const dy = member.point.y - group.anchor.y;
                        const distanceSquared = dx * dx + dy * dy;
                        if (distanceSquared <= thresholdSquared && distanceSquared < selectedDistanceSquared) {
                            selectedGroup = group;
                            selectedDistanceSquared = distanceSquared;
                        }
                    });
                }
            }

            if (selectedGroup) {
                selectedGroup.members.push(member);
                return;
            }

            const group = { anchor: member.point, members: [member] };
            groups.push(group);
            const key = cellKey(cellX, cellY);
            if (!grid.has(key)) grid.set(key, []);
            grid.get(key).push(group);
        });

        return { groups: groups, useProjection: located.useProjection };
    }

    _unprojectDisplayPoint(point, useProjection) {
        if (useProjection) {
            const latLng = this.map.unproject(point, this.referenceZoom);
            return { lat: Number(latLng.lat), lon: Number(latLng.lng) };
        }
        return { lat: point.y, lon: point.x };
    }

    _layoutGroup(group, useProjection) {
        if (group.members.length === 1) {
            const entry = group.members[0].entry;
            return [{ lat: entry.lat, lon: entry.lon, markerData: entry }];
        }

        const origin = group.members[0].point;
        const centerOffset = group.members.reduce((total, member) => ({
            x: total.x + (member.point.x - origin.x),
            y: total.y + (member.point.y - origin.y)
        }), { x: 0, y: 0 });
        const center = {
            x: origin.x + centerOffset.x / group.members.length,
            y: origin.y + centerOffset.y / group.members.length
        };
        const fallbackRadius = this.offsetRadius * 360 / (256 * Math.pow(2, this.referenceZoom));
        const radius = useProjection ? this.offsetRadius : fallbackRadius;

        return group.members.map((member, index) => {
            let dx = member.point.x - center.x;
            let dy = member.point.y - center.y;
            const distance = Math.sqrt(dx * dx + dy * dy);

            if (distance > MARKER_OVERLAP_POINT_EPSILON_PX) {
                dx /= distance;
                dy /= distance;
            } else {
                const angle = (2 * Math.PI * index) / group.members.length;
                dx = Math.cos(angle);
                dy = Math.sin(angle);
            }

            const display = this._unprojectDisplayPoint({
                x: member.point.x + radius * dx,
                y: member.point.y + radius * dy
            }, useProjection);
            return { lat: display.lat, lon: display.lon, markerData: member.entry };
        });
    }

    /**
     * Returns stable display coordinates without creating Leaflet markers.
     */
    getClusteredData() {
        // At lower zooms the stable reference-zoom offset is subpixel. Avoid
        // projecting and grouping thousands of markers for no visible result.
        if (!this._hasVisibleLayoutOffset()) {
            return this.entries.map((entry) => ({
                lat: entry.lat,
                lon: entry.lon,
                markerData: entry
            }));
        }
        const layout = this._buildGroups();
        return layout.groups.flatMap((group) => this._layoutGroup(group, layout.useProjection));
    }

}

// These styles depend only on the canonical contract, never on backend payload fields.
function getEntityStyle(entity) {
    const colors = AppConstants.COLORS || {};
    const palette = {
        atlas: [colors.ATLAS_MATCHED || '#174092', colors.ATLAS_UNMATCHED || '#DC3545'],
        osm: [colors.OSM_MATCHED || '#4CAF50', colors.OSM_UNMATCHED || '#6C757D'],
        gtfs: [colors.GTFS_MATCHED || '#F0AD4E', colors.GTFS_UNMATCHED || '#6C757D']
    };
    const color = palette[entity.entityType][entity.status === 'unmatched' ? 1 : 0];
    const isGtfs = entity.entityType === 'gtfs';
    return {
        color, fillColor: color,
        radius: isGtfs ? 5 : AppConstants.MARKERS.DEFAULT_RADIUS,
        weight: isGtfs ? 1.5 : AppConstants.MARKERS.DEFAULT_WEIGHT,
        opacity: entity.emphasis === 'subdued' ? 0.4 : entity.emphasis === 'context' ? 0.6 : 1,
        fillOpacity: entity.emphasis === 'subdued' ? 0.2 : entity.emphasis === 'context' ? 0.6 : (isGtfs ? 0.85 : AppConstants.MARKERS.DEFAULT_FILL_OPACITY)
    };
}

function getEntityRenderSignature(entity, zoom) {
    const style = getEntityStyle(entity);
    const label = zoom >= MAP_RENDERER_LABEL_ICON_MIN_ZOOM ? entity.label : null;
    return [entity.entityType, style.color, label || 'circle', entity.emphasis].join('|');
}

function layoutEntities(entities, options = {}) {
    const zoom = options.zoom ?? (options.map && options.map.getZoom());
    const manager = new MarkerClusterManager({ map: options.map, zoom });
    entities.forEach(entity => manager.addMarker(...entity.sourcePosition, { key: entity.key, entityType: entity.entityType, entity }));
    const entries = options.overlap === false
        ? manager.entries.map(entry => ({ lat: entry.lat, lon: entry.lon, markerData: entry }))
        : manager.getClusteredData();
    const displayPositionsByKey = new Map(options.sourcePositionsByKey || []);
    const descriptors = entries.map(entry => {
        const entity = entry.markerData.entity;
        const displayPosition = Object.freeze([entry.lat, entry.lon]);
        displayPositionsByKey.set(entity.key, displayPosition);
        // The registry uses position for validation and default marker updates.
        return { key: entity.key, entity, position: displayPosition, displayPosition, zoom,
            renderSignature: getEntityRenderSignature(entity, zoom) };
    });
    return { descriptors, displayPositionsByKey };
}

function createEntityMarker(descriptor) {
    const { entity, displayPosition, zoom } = descriptor;
    const style = getEntityStyle(entity);
    if (entity.label && zoom >= MAP_RENDERER_LABEL_ICON_MIN_ZOOM) {
        const icon = getCachedLabeledCircleIcon(entity.entityType, style.color, entity.label,
            style.radius * 2, style.radius, style.weight, style.fillOpacity);
        return L.marker(displayPosition, { icon, opacity: style.opacity });
    }
    return L.circleMarker(displayPosition, style);
}

function addLayersInChunks(layer, markers, batchSize = 200) {
    let currentIndex = 0;
    let timeoutId = null;
    let cancelled = false;
    let settle;
    const complete = new Promise(resolve => { settle = resolve; });

    function finish(status) {
        if (!settle) return;
        const resolve = settle;
        settle = null;
        resolve({ status: status, added: currentIndex });
    }

    function addNextChunk() {
        timeoutId = null;
        if (cancelled) {
            finish('cancelled');
            return;
        }
        const end = Math.min(currentIndex + batchSize, markers.length);
        for (let i = currentIndex; i < end; i++) {
            try { layer.addLayer(markers[i]); } catch (e) { }
        }
        currentIndex = end;
        if (currentIndex < markers.length) {
            timeoutId = setTimeout(addNextChunk, 0);
        } else {
            finish('complete');
        }
    }
    addNextChunk();
    return {
        complete: complete,
        cancel: function() {
            if (cancelled || !settle) return;
            cancelled = true;
            if (timeoutId != null) clearTimeout(timeoutId);
            timeoutId = null;
            finish('cancelled');
        }
    };
}

function renderEntities(entities, layer, options = {}) {
    const layout = options.layout || layoutEntities(entities, options);
    const markers = layout.descriptors.map(descriptor => {
        const marker = createEntityMarker(descriptor);
        if (options.bindPopup) options.bindPopup(marker, descriptor.entity);
        if (!options.batchAdd) layer.addLayer(marker);
        return marker;
    });
    if (options.batchAdd) {
        const batch = addLayersInChunks(layer, markers, options.batchSize || 200);
        Object.defineProperties(markers, {
            batchComplete: { value: batch.complete }, cancelBatch: { value: batch.cancel }
        });
    }
    return markers;
}

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

window.MapRenderer = Object.freeze({
    MarkerClusterManager: MarkerClusterManager,
    getEntityStyle: getEntityStyle,
    layoutEntities: layoutEntities,
    createEntityMarker: createEntityMarker,
    renderEntities: renderEntities,
    getEntityRenderSignature: getEntityRenderSignature,
    createPopupWithOptions: createPopupWithOptions
});
window.MapComponents = window.MapComponents || {};
window.MapComponents.MapRenderer = window.MapRenderer;
