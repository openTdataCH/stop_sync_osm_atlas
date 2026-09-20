// Draw canonical relationships using the same keyed display positions as markers.
(function (global) {
    'use strict';
    function drawLine(layer, fromLat, fromLon, toLat, toLon, style) {
        const line = L.polyline([[fromLat, fromLon], [toLat, toLon]], style);
        layer.addLayer(line);
        return line;
    }

    function drawRelationships(relationships, layer, positions, options = {}) {
        const colors = AppConstants.COLORS || {};
        const zoom = options.currentZoom ?? Infinity;
        if (zoom < (options.minZoom ?? 0) || options.showOsm === false) return 0;
        const groupMinZoom = (AppConstants.MAP && AppConstants.MAP.ZOOM_OSM_GROUP_LINE_THRESHOLD) || 17;
        const seen = new Set();
        let count = 0;
        relationships.forEach(edge => {
            if (seen.has(edge.key)) return;
            const group = edge.relationshipType === 'group_link';
            if (group ? zoom < groupMinZoom : options.showAtlas === false) return;
            const from = positions.get(edge.fromKey), to = positions.get(edge.toKey);
            if (!from || !to) return;
            seen.add(edge.key);
            const style = { color: group ? (colors.LINE_OSM_GROUP || '#4CAF50')
                : edge.relationshipType === 'gtfs_identity' ? (colors.GTFS_MATCHED || '#F0AD4E')
                    : (colors.LINE_ATLAS_OSM || '#174092'),
                weight: 2, opacity: group ? 0.9 : options.isContext ? 0.4 : 1 };
            if (group) style.dashArray = colors.LINE_OSM_GROUP_DASH || '6,4';
            drawLine(layer, ...from, ...to, style);
            count++;
        });
        return count;
    }

    global.LineRenderer = Object.freeze({ drawLine, drawRelationships,
        clearLines: layer => { if (layer) layer.clearLayers(); } });
    global.MapComponents = global.MapComponents || {};
    global.MapComponents.LineRenderer = global.LineRenderer;
})(window);
