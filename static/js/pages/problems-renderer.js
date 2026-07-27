// Focused problem rendering belongs to the Problems feature, not the shared map renderer.
(function (global) {
    'use strict';

    const colors = (global.AppConstants && global.AppConstants.COLORS) || {};
    const COLOR_ATLAS_MATCHED = colors.ATLAS_MATCHED || '#174092';
    const COLOR_OSM_MATCHED = colors.OSM_MATCHED || '#4CAF50';
    const COLOR_ATLAS_UNMATCHED = colors.ATLAS_UNMATCHED || '#DC3545';
    const COLOR_OSM_UNMATCHED = colors.OSM_UNMATCHED || '#6C757D';
    const COLOR_LINE_ATLAS_OSM = colors.LINE_ATLAS_OSM || COLOR_ATLAS_MATCHED;

    function requireDependencies() {
        if (!global.MapRenderer || !global.PopupRenderer) {
            throw new Error('ProblemsRenderer requires MapRenderer and PopupRenderer.');
        }
    }

    function bindPopup(marker, html) {
        marker.bindPopup(global.MapRenderer.createPopupWithOptions(html));
        return marker;
    }

    function drawMatchedProblem(map, stop, layers, fitView) {
        const positions = [
            [stop.atlas_lat, stop.atlas_lon],
            [stop.osm_lat, stop.osm_lon]
        ];
        if (fitView) {
            map.fitBounds(L.latLngBounds(positions).pad(0.2));
        }

        // Marker representation and projected overlap positions must be chosen
        // for the final view, not for the previous problem's zoom.
        const zoom = map.getZoom();
        const atlasMarker = global.MapRenderer.createAtlasMarker(
            stop.atlas_lat,
            stop.atlas_lon,
            COLOR_ATLAS_MATCHED,
            stop.has_atlas_duplicate,
            zoom
        );
        bindPopup(atlasMarker, global.PopupRenderer.generatePopupHtml(stop, 'atlas')).addTo(layers.markersLayer);

        const osmMarker = global.MapRenderer.createOsmMarker(
            stop.osm_lat,
            stop.osm_lon,
            COLOR_OSM_MATCHED,
            stop.osm_node_type,
            zoom
        );
        bindPopup(osmMarker, global.PopupRenderer.generatePopupHtml(stop, 'osm')).addTo(layers.markersLayer);

        const line = L.polyline(
            positions,
            { color: COLOR_LINE_ATLAS_OSM, weight: 2 }
        ).addTo(layers.linesLayer);
        atlasMarker.openPopup();
    }

    function drawUnmatchedProblem(map, stop, layers, fitView) {
        if (stop.stop_type === 'atlas_unmatched' && stop.atlas_lat != null && stop.atlas_lon != null) {
            if (fitView) map.setView([stop.atlas_lat, stop.atlas_lon], 16);
            const zoom = map.getZoom();
            const marker = global.MapRenderer.createAtlasMarker(
                stop.atlas_lat,
                stop.atlas_lon,
                COLOR_ATLAS_UNMATCHED,
                stop.has_atlas_duplicate,
                zoom
            );
            bindPopup(marker, global.PopupRenderer.generateSingleAtlasBubbleHtml(stop, true)).addTo(layers.markersLayer);
            marker.openPopup();
            return;
        }

        if (stop.stop_type === 'osm_unmatched' && stop.osm_lat != null && stop.osm_lon != null) {
            if (fitView) map.setView([stop.osm_lat, stop.osm_lon], 16);
            const zoom = map.getZoom();
            const marker = global.MapRenderer.createOsmMarker(
                stop.osm_lat,
                stop.osm_lon,
                COLOR_OSM_UNMATCHED,
                stop.osm_node_type,
                zoom
            );
            bindPopup(marker, global.PopupRenderer.generateSingleOsmBubbleHtml(stop, true)).addTo(layers.markersLayer);
            marker.openPopup();
        }
    }

    function drawDuplicateProblem(map, stop, layers, fitView) {
        const members = Array.isArray(stop.members) ? stop.members : [];
        const points = [];
        const markerData = [];
        const isOsmGroup = stop.group_type === 'osm';
        const isAtlasGroup = stop.group_type === 'atlas';

        members.forEach(function (member) {
            if (!isOsmGroup && member.atlas_lat != null && member.atlas_lon != null) {
                const color = member.stop_type === 'atlas_unmatched' ? COLOR_ATLAS_UNMATCHED : COLOR_ATLAS_MATCHED;
                markerData.push({
                    key: 'atlas:' + String(member.sloid || member.id),
                    lat: Number(member.atlas_lat),
                    lon: Number(member.atlas_lon),
                    type: 'atlas',
                    color: color,
                    hasAtlasDuplicate: member.has_atlas_duplicate,
                    stopData: member,
                    popup: global.MapRenderer.createPopupWithOptions(global.PopupRenderer.generatePopupHtml(member, 'atlas'))
                });
                points.push([member.atlas_lat, member.atlas_lon]);
            }
            if (!isAtlasGroup && member.osm_lat != null && member.osm_lon != null) {
                markerData.push({
                    key: 'osm:' + String(member.osm_node_id || member.id),
                    lat: Number(member.osm_lat),
                    lon: Number(member.osm_lon),
                    type: 'osm',
                    color: COLOR_OSM_MATCHED,
                    osmNodeType: member.osm_node_type,
                    stopData: member,
                    popup: global.MapRenderer.createPopupWithOptions(global.PopupRenderer.generatePopupHtml(member, 'osm'))
                });
                points.push([member.osm_lat, member.osm_lon]);
            }
        });

        if (fitView && points.length > 0) {
            map.fitBounds(L.latLngBounds(points).pad(0.2));
        }
        const markers = global.MapRenderer.createMarkersWithOverlapHandling(markerData, layers.markersLayer, {
            map: map,
            zoom: map.getZoom()
        });
        markers.slice(0, 6).forEach(function (marker) {
            if (typeof marker.openPopup === 'function') marker.openPopup();
        });
    }

    function drawProblemOnMap(map, problemData, layers, options) {
        requireDependencies();
        options = options || {};
        const fitView = options.fitView !== false;
        layers.markersLayer.clearLayers();
        layers.linesLayer.clearLayers();
        if (!problemData) return;

        const isMatchedProblem = (
            problemData.problem === 'distance' ||
            problemData.problem === 'attributes' ||
            problemData.problem === 'contradicts_route_matching'
        ) && problemData.stop_type === 'matched' &&
            problemData.atlas_lat != null && problemData.atlas_lon != null &&
            problemData.osm_lat != null && problemData.osm_lon != null;

        if (isMatchedProblem) {
            drawMatchedProblem(map, problemData, layers, fitView);
        } else if (problemData.problem === 'unmatched') {
            drawUnmatchedProblem(map, problemData, layers, fitView);
        } else if (problemData.problem === 'duplicates') {
            drawDuplicateProblem(map, problemData, layers, fitView);
        }
    }

    global.ProblemsRenderer = Object.freeze({ drawProblemOnMap: drawProblemOnMap });
})(window);
