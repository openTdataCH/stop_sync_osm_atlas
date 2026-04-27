(function (global) {
    'use strict';

    const PopupRenderer = {};
    const COLLAPSIBLE_DEFAULT_EXPANDED = false;
    const OSM_NODE_TYPE_MAP = {
        railway_station: 'Railway Station',
        ferry_terminal: 'Ferry Terminal',
        aerialway: 'Aerialway',
        platform: 'Platform',
        stop_position: 'Stop Position'
    };

    function hasValue(value) {
        return value !== undefined && value !== null && value !== '';
    }

    function formatDistanceMeters(distanceM) {
        if (!hasValue(distanceM)) return null;
        const parsed = parseFloat(distanceM);
        if (Number.isNaN(parsed)) return null;
        return `${parsed.toFixed(1)} m`;
    }

    function formatCoords(lat, lon) {
        if (!hasValue(lat) || !hasValue(lon)) return null;
        return `(${lat}, ${lon})`;
    }

    function parseOsmElementRef(osmId) {
        if (!hasValue(osmId)) return null;

        const value = String(osmId);
        if (value.startsWith('way_')) {
            return { type: 'way', id: value.slice(4) };
        }

        return { type: 'node', id: value };
    }

    function buildOsmBrowseUrl(osmId) {
        const ref = parseOsmElementRef(osmId);
        if (!ref) return null;
        return `https://www.openstreetmap.org/${ref.type}/${ref.id}`;
    }

    function buildOsmEditorUrl(osmId) {
        const ref = parseOsmElementRef(osmId);
        if (!ref) return null;
        return `https://www.openstreetmap.org/edit?${ref.type}=${ref.id}`;
    }

    function getMatchDocUrl(matchType) {
        if (!matchType) return null;
        const mt = String(matchType).toLowerCase();
        if (mt.startsWith('exact')) return '/docs/2.1%20Exact%20matching.md';
        if (mt.includes('name')) return '/docs/2.2%20Name%20matching.md';
        if (mt.includes('distance')) return '/docs/2.3%20Distance%20matching.md';
        if (mt.startsWith('route')) return '/docs/2.4%20Route%20Matching.md';
        return null;
    }

    function buildMatchTypeHtml(matchType) {
        const text = matchType || 'N/A';
        const docUrl = getMatchDocUrl(text);
        if (!docUrl) return text;
        return `${text} <a href="${docUrl}" class="matchtype-doc-link" target="_blank" rel="noopener noreferrer" title="Open docs for this matching method"><i class="fas fa-info-circle"></i></a>`;
    }

    function getOsmTypeDisplay(data, withFallback) {
        if (hasValue(data.osm_node_type) && OSM_NODE_TYPE_MAP[data.osm_node_type]) {
            return OSM_NODE_TYPE_MAP[data.osm_node_type];
        }

        const transportTypes = [];
        if (data.osm_amenity === 'ferry_terminal') transportTypes.push('Ferry Terminal');
        if (data.osm_aerialway === 'station') transportTypes.push('Aerialway Station');
        if (data.osm_railway === 'tram_stop') transportTypes.push('Tram Stop');
        if (data.osm_public_transport === 'station') transportTypes.push('Station');
        if (data.osm_public_transport === 'platform') transportTypes.push('Platform');
        if (data.osm_public_transport === 'stop_position') transportTypes.push('Stop Position');

        if (transportTypes.length > 0) return transportTypes.join(', ');
        return withFallback ? 'N/A' : null;
    }

    function stopHasMatches(stop) {
        if (!stop || stop.stop_type !== 'matched') return false;
        if (Array.isArray(stop.atlas_matches) && stop.atlas_matches.length > 0) return true;
        if (Array.isArray(stop.osm_matches) && stop.osm_matches.length > 0) return true;
        return hasValue(stop.atlas_lat) && hasValue(stop.osm_lat);
    }

    function buildBubbleHeader(data, type, unmatched) {
        let headerText = unmatched ? 'Unmatched ' : '';
        let linkHtml = '';

        if (type === 'atlas') {
            headerText += 'ATLAS Stop';
            if (hasValue(data.uic_ref)) {
                linkHtml = ` <a href="https://atlas.app.sbb.ch/service-point-directory/service-points/${data.uic_ref}/traffic-point-elements" target="_blank" title="View on SBB ATLAS">(view on ATLAS)</a>`;
            }
        } else {
            headerText += 'OSM Node';
            if (hasValue(data.osm_node_id)) {
                const browseUrl = buildOsmBrowseUrl(data.osm_node_id);
                if (browseUrl) {
                    linkHtml = ` <a href="${browseUrl}" target="_blank" title="View on OpenStreetMap">(view on OSM)</a>`;
                }
            }
        }

        return `<h5>${headerText}${linkHtml}</h5>`;
    }

    function buildRoutesFooterHtml(data, type, unmatched, hideRoutesAndNotes, actionButtonHtml) {
        if (hideRoutesAndNotes) {
            return actionButtonHtml ? `<div class="bubble-footer"><div class="bubble-btn-row">${actionButtonHtml}</div></div>` : '';
        }

        const routes = type === 'atlas' ? data.routes_atlas : data.routes_osm;
        const formattedRoutes = type === 'atlas'
            ? PopupUtils.formatAtlasRouteList(routes)
            : PopupUtils.formatRouteList(routes);
        const collapsible = PopupUtils.createCollapsible('Routes', formattedRoutes, COLLAPSIBLE_DEFAULT_EXPANDED);
        const buttons = `${collapsible.buttonHtml || ''}${actionButtonHtml || ''}`;

        if (!buttons && !collapsible.panelHtml) return '';

        return `
            <div class="bubble-footer">
                ${buttons ? `<div class="bubble-btn-row">${buttons}</div>` : ''}
                ${collapsible.panelHtml || ''}
            </div>`;
    }

    function buildAtlasRows(data, unmatched) {
        const rows = [];
        const link = PopupUtils.createFilterLink;
        const mismatchText = data.isOperatorMismatch && !unmatched
            ? ' <span class="operator-mismatch">(!Operator Mismatch!)</span>'
            : '';

        rows.push(['Sloid', unmatched ? data.sloid : link(data.sloid, 'atlas')]);
        if (hasValue(data.uic_ref)) rows.push(['UIC Ref', link(data.uic_ref, 'station')]);
        rows.push(['Name', data.atlas_designation_official || 'N/A']);
        rows.push(['Designation', data.atlas_designation || 'N/A']);
        rows.push(['Business Org', `${data.atlas_business_org_abbr || 'N/A'}${mismatchText}`]);

        const coords = formatCoords(data.atlas_lat, data.atlas_lon);
        if (coords) rows.push(['Coord', coords]);

        if (!unmatched) {
            const distance = formatDistanceMeters(data.distance_m);
            if (distance) rows.push(['Distance', distance]);
            rows.push(['Match Type', buildMatchTypeHtml(data.match_type)]);
        }

        return rows;
    }

    function buildOsmRows(data, unmatched) {
        const rows = [];
        const link = PopupUtils.createFilterLink;
        const mismatchText = data.isOperatorMismatch && !unmatched
            ? ' <span class="operator-mismatch">(!Operator Mismatch!)</span>'
            : '';

        rows.push(['Node ID', unmatched ? data.osm_node_id : link(data.osm_node_id, 'osm')]);

        if (unmatched) {
            if (hasValue(data.uic_ref)) rows.push(['UIC Ref', link(data.uic_ref, 'station')]);
            if (hasValue(data.osm_uic_ref)) rows.push(['OSM UIC Ref', data.osm_uic_ref]);
            rows.push(['Name', data.osm_name || 'N/A']);
            rows.push(['UIC Name', data.osm_uic_name || 'N/A']);
            rows.push(['Network', data.osm_network || 'N/A']);
            rows.push(['Operator', data.osm_operator || 'N/A']);
            rows.push(['Type', getOsmTypeDisplay(data, true)]);
            rows.push(['Local Ref', data.osm_local_ref || 'N/A']);
            return rows;
        }

        if (hasValue(data.osm_uic_ref)) {
            const diffLabel = hasValue(data.uic_ref) && data.uic_ref !== data.osm_uic_ref
                ? ' <span class="uic-mismatch">(differs)</span>'
                : '';
            rows.push(['OSM UIC Ref', `${data.osm_uic_ref}${diffLabel}`]);
        }
        rows.push(['Name', data.osm_name || 'N/A']);
        if (hasValue(data.osm_uic_name)) rows.push(['UIC Name', data.osm_uic_name]);
        if (hasValue(data.osm_local_ref)) rows.push(['Local Ref', data.osm_local_ref]);
        if (hasValue(data.osm_network)) rows.push(['Network', data.osm_network]);
        if (hasValue(data.osm_operator)) rows.push(['Operator', `${data.osm_operator}${mismatchText}`]);

        const osmType = getOsmTypeDisplay(data, false);
        if (osmType) rows.push(['Type', osmType]);

        const coords = formatCoords(data.osm_lat, data.osm_lon);
        if (coords) rows.push(['Coord', coords]);

        const distance = formatDistanceMeters(data.distance_m);
        if (distance) rows.push(['Distance', distance]);

        rows.push(['Match Type', buildMatchTypeHtml(data.match_type)]);
        return rows;
    }

    function renderBubble(data, opts) {
        const { type, unmatched = false, hideRoutesAndNotes = false, actionButtonHtml = '' } = opts;
        if (!type) throw new Error('PopupRenderer.renderBubble - type is required');

        const rows = type === 'atlas' ? buildAtlasRows(data, unmatched) : buildOsmRows(data, unmatched);
        const tableRowsHtml = rows.map(([label, value]) => `<tr><td>${label}:</td><td>${value}</td></tr>`).join('');
        const bubbleClass = type === 'atlas' ? 'atlas-match' : 'osm-match';
        const unmatchedClass = unmatched ? ' unmatched' : '';
        const bubbleHeader = buildBubbleHeader(data, type, unmatched);

        const osmEditorUrl = type === 'osm' ? buildOsmEditorUrl(data.osm_node_id) : null;
        const osmEditorLinkHtml = osmEditorUrl
            ? `<div class="osm-editor-link-container mt-2"><a href="${osmEditorUrl}" class="osm-editor-link" target="_blank" rel="noopener noreferrer"><i class="fas fa-external-link-alt"></i> Edit in OSM iD Editor</a></div>`
            : '';
        const footerHtml = buildRoutesFooterHtml(data, type, unmatched, hideRoutesAndNotes, actionButtonHtml);

        return `
            <div class="${bubbleClass}${unmatchedClass}">
                <div class="bubble-body">
                    ${bubbleHeader}
                    <table class="popup-table">${tableRowsHtml}</table>
                    ${osmEditorLinkHtml}
                    ${footerHtml}
                </div>
            </div>`;
    }

    function wrapSingleBubble(innerHtml, type, stopId) {
        return `<div class="popup-content-container" data-stop-id="${stopId}" data-type="${type}">${innerHtml}</div>`;
    }

    function buildAtlasDataFromStop(stop) {
        return {
            id: stop.id,
            sloid: stop.sloid,
            uic_ref: stop.uic_ref,
            osm_uic_ref: stop.osm_uic_ref,
            atlas_designation: stop.atlas_designation,
            atlas_designation_official: stop.atlas_designation_official,
            atlas_business_org_abbr: stop.atlas_business_org_abbr,
            atlas_lat: stop.atlas_lat,
            atlas_lon: stop.atlas_lon,
            distance_m: stop.distance_m,
            match_type: stop.match_type,
            routes_atlas: stop.routes_atlas,
            stop_type: stop.stop_type,
            isOperatorMismatch: stop.isOperatorMismatch
        };
    }

    function buildOsmDataFromStop(stop) {
        if (stop.is_osm_node) {
            const firstAtlas = Array.isArray(stop.atlas_matches) && stop.atlas_matches.length > 0
                ? stop.atlas_matches[0]
                : null;
            return {
                id: stop.id,
                osm_node_id: stop.osm_node_id,
                uic_ref: stop.uic_ref,
                osm_name: stop.osm_name,
                osm_uic_name: stop.osm_uic_name,
                osm_uic_ref: stop.osm_uic_ref,
                osm_local_ref: stop.osm_local_ref,
                osm_network: stop.osm_network,
                osm_operator: stop.osm_operator,
                osm_public_transport: stop.osm_public_transport,
                osm_amenity: stop.osm_amenity,
                osm_aerialway: stop.osm_aerialway,
                osm_railway: stop.osm_railway,
                osm_lat: stop.osm_lat,
                osm_lon: stop.osm_lon,
                distance_m: firstAtlas ? firstAtlas.distance_m : stop.distance_m,
                match_type: stop.match_type || (firstAtlas ? firstAtlas.match_type : null),
                routes_osm: stop.routes_osm,
                stop_type: stop.stop_type,
                isOperatorMismatch: stop.isOperatorMismatch
            };
        }

        if (Array.isArray(stop.osm_matches) && stop.osm_matches.length > 0) {
            const representative = stop.osm_matches[0] || {};
            return {
                id: representative.osm_id || stop.id,
                osm_node_id: representative.osm_node_id,
                uic_ref: stop.uic_ref,
                osm_name: representative.osm_name || stop.osm_name,
                osm_uic_name: representative.osm_uic_name || stop.osm_uic_name,
                osm_uic_ref: representative.osm_uic_ref || stop.osm_uic_ref,
                osm_local_ref: representative.osm_local_ref || stop.osm_local_ref,
                osm_network: representative.osm_network || stop.osm_network,
                osm_operator: representative.osm_operator || stop.osm_operator,
                osm_public_transport: representative.osm_public_transport || stop.osm_public_transport,
                osm_amenity: representative.osm_amenity || stop.osm_amenity,
                osm_aerialway: representative.osm_aerialway || stop.osm_aerialway,
                osm_railway: representative.osm_railway || stop.osm_railway,
                osm_lat: representative.osm_lat || stop.osm_lat,
                osm_lon: representative.osm_lon || stop.osm_lon,
                distance_m: representative.distance_m || stop.distance_m,
                match_type: representative.match_type || stop.match_type,
                routes_osm: representative.routes_osm || stop.routes_osm,
                stop_type: stop.stop_type,
                isOperatorMismatch: stop.isOperatorMismatch
            };
        }

        return {
            id: stop.id,
            osm_node_id: stop.osm_node_id,
            uic_ref: stop.uic_ref,
            osm_name: stop.osm_name,
            osm_uic_name: stop.osm_uic_name,
            osm_uic_ref: stop.osm_uic_ref,
            osm_local_ref: stop.osm_local_ref,
            osm_network: stop.osm_network,
            osm_operator: stop.osm_operator,
            osm_public_transport: stop.osm_public_transport,
            osm_amenity: stop.osm_amenity,
            osm_aerialway: stop.osm_aerialway,
            osm_railway: stop.osm_railway,
            osm_lat: stop.osm_lat,
            osm_lon: stop.osm_lon,
            distance_m: stop.distance_m,
            match_type: stop.match_type,
            routes_osm: stop.routes_osm,
            stop_type: stop.stop_type,
            isOperatorMismatch: stop.isOperatorMismatch
        };
    }

    function buildUnifiedBubbleSpecs(stop) {
        if (!stop || stop.stop_type !== 'matched') return [];

        const specs = [];
        if (stop.is_osm_node && Array.isArray(stop.atlas_matches) && stop.atlas_matches.length > 0) {
            specs.push({ type: 'osm', data: buildOsmDataFromStop(stop) });
            stop.atlas_matches.forEach(atlasMatch => {
                specs.push({
                    type: 'atlas',
                    data: {
                        ...atlasMatch,
                        id: stop.id,
                        uic_ref: atlasMatch.uic_ref,
                        isOperatorMismatch: stop.isOperatorMismatch
                    }
                });
            });
            return specs;
        }

        if (Array.isArray(stop.osm_matches) && stop.osm_matches.length > 0) {
            specs.push({ type: 'atlas', data: buildAtlasDataFromStop(stop) });
            stop.osm_matches.forEach(osmMatch => {
                specs.push({
                    type: 'osm',
                    data: {
                        ...osmMatch,
                        id: osmMatch.osm_id || stop.id,
                        uic_ref: stop.uic_ref,
                        isOperatorMismatch: stop.isOperatorMismatch
                    }
                });
            });
            return specs;
        }

        if (hasValue(stop.atlas_lat) && hasValue(stop.osm_lat)) {
            specs.push({ type: 'atlas', data: buildAtlasDataFromStop(stop) });
            specs.push({ type: 'osm', data: buildOsmDataFromStop(stop) });
        }
        return specs;
    }

    function generateSingleAtlasBubbleHtml(data, isUnmatched = false, options = {}) {
        const inner = renderBubble(data, { type: 'atlas', unmatched: isUnmatched, ...options });
        const stopId = data && (data.id || data.stop_id || '');
        return wrapSingleBubble(inner, 'atlas', stopId);
    }

    function generateSingleOsmBubbleHtml(data, isUnmatched = false, options = {}) {
        const inner = renderBubble(data, { type: 'osm', unmatched: isUnmatched, ...options });
        const stopId = data && (data.id || data.stop_id || '');
        return wrapSingleBubble(inner, 'osm', stopId);
    }

    function generateInitialBubbleHtml(stop, initialViewType, options = {}) {
        const isUnmatched = stop.stop_type === 'atlas_unmatched' || stop.stop_type === 'osm_unmatched';
        const actionButtonHtml = stopHasMatches(stop)
            ? `<button class="btn btn-sm popup-action-btn" onclick='PopupRenderer.showMatches(this, ${stop.id})'>See Matches</button>`
            : '';

        if (initialViewType === 'atlas') {
            return renderBubble(buildAtlasDataFromStop(stop), {
                type: 'atlas',
                unmatched: isUnmatched,
                actionButtonHtml,
                ...options
            });
        }

        if (initialViewType === 'osm') {
            return renderBubble(buildOsmDataFromStop(stop), {
                type: 'osm',
                unmatched: isUnmatched,
                actionButtonHtml,
                ...options
            });
        }

        return '';
    }

    function generateUnifiedBubbleHtml(stop, initialViewType, options = {}) {
        const specs = buildUnifiedBubbleSpecs(stop);
        if (specs.length === 0) return '<!-- No matches to display -->';

        const cardsHtml = specs.map(spec => {
            const bubble = renderBubble(spec.data, { type: spec.type, ...options, actionButtonHtml: '' });
            return `<div class="popup-match-item">${bubble}</div>`;
        }).join('');

        const closeButtonHtml = `<button class="btn btn-sm popup-action-btn" onclick='PopupRenderer.hideMatches(this, ${stop.id}, "${initialViewType}")'>Close Matches</button>`;
        return `
            <div class="matches-container">${cardsHtml}</div>
            <div class="popup-actions mt-2">${closeButtonHtml}</div>`;
    }

    function generatePopupHtml(stop, initialViewType, options = {}) {
        const initialContent = generateInitialBubbleHtml(stop, initialViewType, options);
        const unifiedContent = stopHasMatches(stop)
            ? generateUnifiedBubbleHtml(stop, initialViewType, options)
            : '';

        return `
            <div class="popup-content-container popup-outer-wrapper" data-stop-id="${stop.id}" data-type="${initialViewType}">
                <div class="popup-initial-view" style="display: block;">
                    ${initialContent}
                </div>
                <div class="popup-unified-view" style="display: none;">
                    ${unifiedContent}
                </div>
            </div>`;
    }

    function toggleMatchesView(buttonElement, showUnified) {
        const container = buttonElement.closest('.popup-outer-wrapper');
        if (!container) return;

        const initialView = container.querySelector('.popup-initial-view');
        const unifiedView = container.querySelector('.popup-unified-view');
        if (initialView) initialView.style.display = showUnified ? 'none' : 'block';
        if (unifiedView) unifiedView.style.display = showUnified ? 'block' : 'none';
        container.setAttribute('data-view-mode', showUnified ? 'unified' : 'initial');

        const popupElement = container.closest('.leaflet-popup');
        const popupInstance = popupElement && popupElement._leaflet_popup_instance;
        if (!popupInstance) return;

        if (typeof popupInstance._onContentUpdate === 'function') {
            popupInstance._onContentUpdate();
        }

        setTimeout(() => {
            if (typeof popupInstance._updateLayout === 'function') {
                popupInstance._updateLayout();
            }
            if (typeof popupInstance._updatePosition === 'function') {
                popupInstance._updatePosition();
            }
            if (typeof popupInstance._ensureDragHandleAtTop === 'function') {
                popupInstance._ensureDragHandleAtTop();
            }
        }, 0);
    }

    function showMatches(buttonElement, stopId) {
        toggleMatchesView(buttonElement, true);
    }

    function hideMatches(buttonElement, stopId, initialViewType) {
        toggleMatchesView(buttonElement, false);
    }

    PopupRenderer.renderBubble = renderBubble;
    PopupRenderer.generateSingleAtlasBubbleHtml = generateSingleAtlasBubbleHtml;
    PopupRenderer.generateSingleOsmBubbleHtml = generateSingleOsmBubbleHtml;
    PopupRenderer.generateInitialBubbleHtml = generateInitialBubbleHtml;
    PopupRenderer.generateUnifiedBubbleHtml = generateUnifiedBubbleHtml;
    PopupRenderer.generatePopupHtml = generatePopupHtml;
    PopupRenderer.showMatches = showMatches;
    PopupRenderer.hideMatches = hideMatches;
    global.PopupRenderer = PopupRenderer;
})(window);


