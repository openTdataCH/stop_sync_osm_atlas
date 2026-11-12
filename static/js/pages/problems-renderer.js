// Focus/navigation and eager popup models belong to Problems, not the shared renderer.
(function (global) {
    'use strict';

    const VIEW_MARGIN_PX = 8;
    // Space a stop popup takes above its marker, kept free when matched stops are fitted.
    const POPUP_ROOM_PX = 340;
    // Space kept below the lowest marker, so its circle or label stays clear of the problem panel.
    const MARKER_CLEARANCE_PX = 16;
    // Height left to the stops themselves on short screens, so a matched pair is not fitted into a sliver.
    const MIN_STOPS_BAND_PX = 120;

    // The rows of the map left visible by the page's toolbar (top) and problem panel (bottom).
    function visibleBand(map, options) {
        const insets = options.viewInsets ? options.viewInsets() : null;
        if (!insets) return null;
        const height = map.getSize().y;
        return { top: insets.top + VIEW_MARGIN_PX, bottom: height - insets.bottom - VIEW_MARGIN_PX };
    }

    // Matched stops and duplicates fit below the room their popup needs and above the panel.
    function fitBoundsOptions(map, band) {
        if (!band) return {};
        const popupRoom = Math.max(0, Math.min(POPUP_ROOM_PX, band.bottom - band.top - MIN_STOPS_BAND_PX));
        return {
            paddingTopLeft: L.point(VIEW_MARGIN_PX, band.top + popupRoom),
            paddingBottomRight: L.point(VIEW_MARGIN_PX, map.getSize().y - band.bottom + MARKER_CLEARANCE_PX),
            // Without animation the popups are measured where they end up.
            animate: false
        };
    }

    // Popups pan the map until they sit between the toolbar and the problem panel,
    // also after the draggable popup adds its Move bar. When a popup is taller than
    // that, Leaflet keeps its top below the toolbar.
    function popupPanOptions(map, band) {
        if (!band) return undefined;
        return {
            autoPan: true,
            autoPanPaddingTopLeft: L.point(VIEW_MARGIN_PX, band.top),
            autoPanPaddingBottomRight: L.point(VIEW_MARGIN_PX, map.getSize().y - band.bottom + MARKER_CLEARANCE_PX)
        };
    }

    function drawProblemOnMap(map, problem, layers, options = {}) {
        layers.markersLayer.clearLayers();
        layers.linesLayer.clearLayers();
        if (!problem) return;
        const duplicate = problem.problem === 'duplicates';
        const matched = ['distance', 'attributes', 'contradicts_route_matching', 'identifier'].includes(problem.problem)
            && problem.stop_type === 'matched';
        const disused = problem.problem === 'disused';
        // An identifier problem on an unmatched element is drawn like that element.
        if (!duplicate && !matched && !disused && !['unmatched', 'identifier'].includes(problem.problem)) return;
        const models = new Map();
        const entities = [];
        // A duplicate group draws its members; a stop's own duplicate problem has none and is drawn as that stop.
        const rows = duplicate && Array.isArray(problem.members) ? problem.members : [problem];
        rows.forEach(stop => ['atlas', 'osm'].forEach(type => {
            if (duplicate && problem.group_type && problem.group_type !== type) return;
            if (!duplicate && !matched && problem.stop_type !== type + (disused ? '_disused' : '_unmatched')) return;
            const entity = global.MapEntityAdapters.stopEntity(type, stop, { emphasis: 'focused' });
            if (!entity || models.has(entity.key)) return;
            entities.push(entity);
            models.set(entity.key, stop);
        }));
        if (!entities.length) return;
        const band = options.fitView !== false ? visibleBand(map, options) : null;
        if (options.fitView !== false) {
            if (!matched && !duplicate) map.setView(entities[0].sourcePosition, 16, band ? { animate: false } : undefined);
            else map.fitBounds(L.latLngBounds(entities.map(entity => entity.sourcePosition)).pad(0.2), fitBoundsOptions(map, band));
        }
        const layout = global.MapRenderer.layoutEntities(entities, {
            map, zoom: map.getZoom(), overlap: duplicate
        });
        const markers = global.MapRenderer.renderEntities(entities, layers.markersLayer, {
            layout,
            bindPopup(marker, entity) {
                const stop = models.get(entity.key);
                const html = !duplicate && !matched
                    ? (entity.entityType === 'atlas' ? global.PopupRenderer.generateSingleAtlasBubbleHtml
                        : global.PopupRenderer.generateSingleOsmBubbleHtml)(stop, true)
                    : global.PopupRenderer.generatePopupHtml(stop, entity.entityType);
                // Duplicates open several popups: only the first one pans, so they do not pull against each other.
                const pans = !duplicate || entity.key === entities[0].key;
                marker.bindPopup(global.MapRenderer.createPopupWithOptions(html, pans ? popupPanOptions(map, band) : undefined));
            }
        });
        if (matched) {
            const snapshot = global.MapEntityAdapters.stops([problem]);
            global.LineRenderer.drawRelationships(snapshot.relationships, layers.linesLayer, layout.displayPositionsByKey);
        }
        markers.slice(0, duplicate ? 6 : 1).forEach(marker => marker.openPopup());
    }

    global.ProblemsRenderer = Object.freeze({ drawProblemOnMap });
})(window);
