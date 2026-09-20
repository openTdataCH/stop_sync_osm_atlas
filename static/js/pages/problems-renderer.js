// Focus/navigation and eager popup models belong to Problems, not the shared renderer.
(function (global) {
    'use strict';

    function drawProblemOnMap(map, problem, layers, options = {}) {
        layers.markersLayer.clearLayers();
        layers.linesLayer.clearLayers();
        if (!problem) return;
        const duplicate = problem.problem === 'duplicates';
        const matched = ['distance', 'attributes', 'contradicts_route_matching'].includes(problem.problem)
            && problem.stop_type === 'matched';
        if (!duplicate && !matched && problem.problem !== 'unmatched') return;
        const models = new Map();
        const entities = [];
        const rows = duplicate ? (problem.members || []) : [problem];
        rows.forEach(stop => ['atlas', 'osm'].forEach(type => {
            if (duplicate && problem.group_type && problem.group_type !== type) return;
            if (!duplicate && !matched && problem.stop_type !== type + '_unmatched') return;
            const entity = global.MapEntityAdapters.stopEntity(type, stop, { emphasis: 'focused' });
            if (!entity || models.has(entity.key)) return;
            entities.push(entity);
            models.set(entity.key, stop);
        }));
        if (!entities.length) return;
        if (options.fitView !== false) {
            if (!matched && !duplicate) map.setView(entities[0].sourcePosition, 16);
            else map.fitBounds(L.latLngBounds(entities.map(entity => entity.sourcePosition)).pad(0.2));
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
                marker.bindPopup(global.MapRenderer.createPopupWithOptions(html));
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
