(function(global){
    'use strict';

    const PopupRenderer = {};

    const COLLAPSIBLE_DEFAULT_EXPANDED = false;

    function renderBubble(data, opts){
        const { type, unmatched = false } = opts;
        if(!type) throw new Error('PopupRenderer.renderBubble – type is required');

        const isAtlas = type === 'atlas';
        const isOsm   = type === 'osm';

        const link = PopupUtils.createFilterLink;
        const routeHtml = (routesArr, isOsmNodeFlag=false) => {
            const formatted = PopupUtils.formatRouteList(routesArr);
            return PopupUtils.createCollapsible('Routes', formatted, COLLAPSIBLE_DEFAULT_EXPANDED);
        };

        const isMismatch = data.isOperatorMismatch === true; 
        const mismatchText = isMismatch ? ' <span class="operator-mismatch">(!Operator Mismatch!)</span>' : '';

        const rows = [];
        let routesSection = '';

        if(isAtlas){
            rows.push(['Sloid', unmatched ? data.sloid : link(data.sloid, 'atlas')]);
            if(data.uic_ref){
                rows.push(['UIC Ref', link(data.uic_ref, 'station')]);
            }
            if(!unmatched && data.osm_uic_ref){
                const diffLabel = (data.uic_ref && data.uic_ref !== data.osm_uic_ref) ? ' <span class="uic-mismatch">(differs)</span>' : '';
                rows.push(['OSM UIC Ref', `${data.osm_uic_ref}${diffLabel}`]);
            }
            rows.push(['Name', data.atlas_designation_official || 'N/A']);
            rows.push(['Local Ref', data.atlas_designation || 'N/A']);
            rows.push(['Business Org', (data.atlas_business_org_abbr || 'N/A') + (isAtlas && !unmatched ? mismatchText : '')]); 
            if(data.atlas_lat && data.atlas_lon){
                rows.push(['Coordinates', `(${data.atlas_lat}, ${data.atlas_lon})`]);
            }
            if(!unmatched){
                if(data.distance_m){
                    rows.push(['Distance', `${parseFloat(data.distance_m).toFixed(1)} m`]);
                }
                rows.push(['Match Type', data.match_type || 'N/A']);
            }
            const unifiedRoutesHtml = PopupUtils.formatUnifiedRouteList(data.routes_unified);
            routesSection = `
                <div class="route-section">
                    ${PopupUtils.createCollapsible('Routes', unifiedRoutesHtml, COLLAPSIBLE_DEFAULT_EXPANDED)}
                </div>
            `;
        }
        if(isOsm){
            rows.push(['Node ID', unmatched ? data.osm_node_id : link(data.osm_node_id, 'osm')]);
            if(!unmatched){
                if(data.uic_ref) rows.push(['UIC Ref (ATLAS)', link(data.uic_ref, 'station')]);
                if(data.osm_uic_ref){
                    const diffLabel = (data.uic_ref && data.uic_ref !== data.osm_uic_ref) ? ' <span class="uic-mismatch">(differs)</span>' : '';
                    rows.push(['OSM UIC Ref', `${data.osm_uic_ref}${diffLabel}`]);
                }
                rows.push(['Name', data.osm_name || 'N/A']);
                if(data.osm_uic_name) rows.push(['UIC Name', data.osm_uic_name]);
                if(data.osm_local_ref) rows.push(['Local Ref', data.osm_local_ref]);
                if(data.osm_network) rows.push(['Network', data.osm_network]);
                if(data.osm_operator) rows.push(['Operator', data.osm_operator + (isOsm && !unmatched ? mismatchText : '')]);
                const typeMap = {
                    'railway_station': 'Railway Station',
                    'ferry_terminal': 'Ferry Terminal',
                    'aerialway': 'Aerialway',
                    'platform': 'Platform',
                    'stop_position': 'Stop Position'
                };
                let displayType = null;
                if (data.osm_node_type && typeMap[data.osm_node_type]) {
                    displayType = typeMap[data.osm_node_type];
                } else {
                    let transportTypes = [];
                    if (data.osm_amenity === 'ferry_terminal') transportTypes.push('Ferry Terminal');
                    if (data.osm_aerialway === 'station') transportTypes.push('Aerialway Station');
                    if (data.osm_railway === 'tram_stop') transportTypes.push('Tram Stop');
                    if (data.osm_public_transport === 'station') transportTypes.push('Station');
                    if (data.osm_public_transport === 'platform') transportTypes.push('Platform');
                    if (data.osm_public_transport === 'stop_position') transportTypes.push('Stop Position');
                    displayType = transportTypes.length > 0 ? transportTypes.join(', ') : null;
                }
                if (displayType) rows.push(['Type', displayType]);
                if(data.osm_lat && data.osm_lon) rows.push(['Coordinates', `(${data.osm_lat}, ${data.osm_lon})`]);
                if(data.distance_m)  rows.push(['Distance', `${parseFloat(data.distance_m).toFixed(1)} m`]);
                rows.push(['Match Type', data.match_type || 'N/A']);
            } else {
                if(data.uic_ref) rows.push(['UIC Ref', link(data.uic_ref, 'station')]);
                if(data.osm_uic_ref) rows.push(['OSM UIC Ref', data.osm_uic_ref]);
                rows.push(['Name', data.osm_name || 'N/A']);
                rows.push(['UIC Name', data.osm_uic_name || 'N/A']);
                rows.push(['Network', data.osm_network || 'N/A']);
                rows.push(['Operator', data.osm_operator || 'N/A']);
                const typeMap = {
                    'railway_station': 'Railway Station',
                    'ferry_terminal': 'Ferry Terminal',
                    'aerialway': 'Aerialway',
                    'platform': 'Platform',
                    'stop_position': 'Stop Position'
                };
                let displayType = 'N/A';
                if (data.osm_node_type && typeMap[data.osm_node_type]) {
                    displayType = typeMap[data.osm_node_type];
                } else {
                    let transportTypes = [];
                    if (data.osm_amenity === 'ferry_terminal') transportTypes.push('Ferry Terminal');
                    if (data.osm_aerialway === 'station') transportTypes.push('Aerialway Station');
                    if (data.osm_railway === 'tram_stop') transportTypes.push('Tram Stop');
                    if (data.osm_public_transport === 'station') transportTypes.push('Station');
                    if (data.osm_public_transport === 'platform') transportTypes.push('Platform');
                    if (data.osm_public_transport === 'stop_position') transportTypes.push('Stop Position');
                    displayType = transportTypes.length > 0 ? transportTypes.join(', ') : 'N/A';
                }
                rows.push(['Type', displayType]);
                rows.push(['Local Ref', data.osm_local_ref || 'N/A']);
            }
            routesSection = `<div class="route-section">${routeHtml(data.routes_osm, isOsm)}</div>`;
        }

        // Add note author if available
        if (isAtlas && data.atlas_note) {
            rows.push(['Note', data.atlas_note]);
            rows.push(['Note Author', data.atlas_note_author_email ? data.atlas_note_author_email : '<em>Not a user</em>']);
        }
        if (isOsm && data.osm_note) {
            rows.push(['Note', data.osm_note]);
            rows.push(['Note Author', data.osm_note_author_email ? data.osm_note_author_email : '<em>Not a user</em>']);
        }

        const tableRowsHtml = rows.map(([k,v]) => `<tr><td>${k}:</td><td>${v}</td></tr>`).join('');

        const bubbleClass = isAtlas ? 'atlas-match' : 'osm-match';
        const unmatchedClass = unmatched ? ' unmatched' : '';
        
        let headerText = unmatched ? 'Unmatched ' : '';
        let linkHtml = '';
        if (isAtlas) {
            headerText += 'ATLAS Stop';
            if (data.uic_ref) {
                 linkHtml = ` <a href="https://atlas.app.sbb.ch/service-point-directory/service-points/${data.uic_ref}/traffic-point-elements" target="_blank" title="View on SBB ATLAS">(view on ATLAS)</a>`;
            }
        } else if (isOsm) {
            headerText += 'OSM Node';
            if (data.osm_node_id) {
                 linkHtml = ` <a href="https://www.openstreetmap.org/node/${data.osm_node_id}" target="_blank" title="View on OpenStreetMap">(view on OSM)</a>`;
            }
        }
        const bubbleHeader = `<h5>${headerText}${linkHtml}</h5>`;

        let extraBtns = '';
        if(unmatched){
            if(isAtlas){
                extraBtns = `<button class="btn btn-sm btn-outline-secondary manual-match-target" type="button" data-stop-id="${data.id}" data-type="atlas">Match to</button>`;
            } else if(isOsm){
                extraBtns = `<button class="btn btn-sm btn-outline-secondary manual-match-target" type="button" data-stop-id="${data.id}" data-type="osm">Match to</button>`;
            }
        }

        return `
            <div class="${bubbleClass}${unmatchedClass}">
                ${bubbleHeader}
                <table class="popup-table">${tableRowsHtml}</table>
                ${routesSection}
                ${extraBtns}
            </div>`;
    }

    function generateSingleAtlasBubbleHtml(data, isUnmatched = false) {
        const inner = renderBubble(data, { type: 'atlas', unmatched: isUnmatched });
        const stopId = data && (data.id || data.stop_id || '');
        return `<div class="popup-content-container" data-stop-id="${stopId}" data-type="atlas">${inner}</div>`;
    }

    function generateSingleOsmBubbleHtml(data, isUnmatched = false) {
        const inner = renderBubble(data, { type: 'osm', unmatched: isUnmatched });
        const stopId = data && (data.id || data.stop_id || '');
        return `<div class="popup-content-container" data-stop-id="${stopId}" data-type="osm">${inner}</div>`;
    }

    function generateInitialBubbleHtml(stop, initialViewType) {
        let initialHtml = '';
        const isMatched = stop.stop_type === 'matched';
        const isUnmatched = stop.stop_type === 'unmatched' || stop.stop_type === 'osm' || stop.stop_type === 'station';

        if (initialViewType === 'atlas') {
            const atlasData = {
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
                routes_unified: stop.routes_unified,
                stop_type: stop.stop_type,
                isOperatorMismatch: stop.isOperatorMismatch
            };
            initialHtml = generateSingleAtlasBubbleHtml(atlasData, isUnmatched);
        } else if (initialViewType === 'osm') {
            let osmData;
            if (stop.is_osm_node) {
                osmData = {
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
                     distance_m: null,
                     match_type: null,
                     routes_osm: stop.routes_osm,
                     stop_type: stop.stop_type,
                     isOperatorMismatch: stop.isOperatorMismatch
                };
            } else if (Array.isArray(stop.osm_matches)) {
                const representativeOsm = stop.osm_matches[0] || {};
                osmData = {
                     id: representativeOsm.osm_id || stop.id,
                     osm_node_id: representativeOsm.osm_node_id,
                     uic_ref: stop.uic_ref,
                     osm_name: representativeOsm.osm_name || stop.osm_name,
                     osm_uic_name: representativeOsm.osm_uic_name || stop.osm_uic_name,
                     osm_uic_ref: representativeOsm.osm_uic_ref || stop.osm_uic_ref,
                     osm_local_ref: representativeOsm.osm_local_ref || stop.osm_local_ref,
                     osm_network: representativeOsm.osm_network || stop.osm_network,
                     osm_operator: representativeOsm.osm_operator || stop.osm_operator,
                     osm_public_transport: representativeOsm.osm_public_transport || stop.osm_public_transport,
                     osm_amenity: representativeOsm.osm_amenity || stop.osm_amenity,
                     osm_aerialway: representativeOsm.osm_aerialway || stop.osm_aerialway,
                     osm_railway: representativeOsm.osm_railway || stop.osm_railway,
                     osm_lat: representativeOsm.osm_lat || stop.osm_lat,
                     osm_lon: representativeOsm.osm_lon || stop.osm_lon,
                     distance_m: representativeOsm.distance_m || stop.distance_m,
                     match_type: representativeOsm.match_type || stop.match_type,
                     routes_osm: representativeOsm.routes_osm || stop.routes_osm,
                     stop_type: stop.stop_type,
                     isOperatorMismatch: stop.isOperatorMismatch
                };
            } else {
                 osmData = {
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
            initialHtml = generateSingleOsmBubbleHtml(osmData, isUnmatched);
        }

        if (isMatched && (stop.atlas_matches || stop.osm_matches || (stop.atlas_lat && stop.osm_lat))) {
            initialHtml += `<div class="popup-actions"><button class="btn btn-sm btn-secondary" onclick='PopupRenderer.showMatches(this, ${stop.id})'>See Matches</button></div>`;
        }
        
        return initialHtml;
    }

    function generateUnifiedBubbleHtml(stop, initialViewType) {
        let unifiedHtml = '<div class="matches-container">';
        let hasMatches = false;

        if (stop.stop_type === 'matched' && stop.is_osm_node && Array.isArray(stop.atlas_matches)) {
            hasMatches = true;
            const osmData = { ...stop, uic_ref: stop.uic_ref };
            unifiedHtml += generateSingleOsmBubbleHtml(osmData, false);
            stop.atlas_matches.forEach((atlasMatch, index) => {
                const atlasData = {
                     ...atlasMatch,
                     id: stop.id,
                     uic_ref: atlasMatch.uic_ref
                };
                unifiedHtml += generateSingleAtlasBubbleHtml(atlasData, false);
            });
        }
        else if (stop.stop_type === 'matched' && Array.isArray(stop.osm_matches)) {
            hasMatches = true;
            const atlasData = { ...stop };
            unifiedHtml += generateSingleAtlasBubbleHtml(atlasData, false);
            stop.osm_matches.forEach((osmMatch, index) => {
                 const osmData = {
                      ...osmMatch,
                      id: osmMatch.osm_id || stop.id,
                      uic_ref: stop.uic_ref
                 };
                 unifiedHtml += generateSingleOsmBubbleHtml(osmData, false);
            });
        }
        else if (stop.stop_type === 'matched' && stop.atlas_lat && stop.osm_lat) {
            hasMatches = true;
            const atlasData = {
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
                routes_unified: stop.routes_unified,
                isOperatorMismatch: stop.isOperatorMismatch
            };
            unifiedHtml += generateSingleAtlasBubbleHtml(atlasData, false);

            const osmData = {
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
                isOperatorMismatch: stop.isOperatorMismatch
            };
            unifiedHtml += generateSingleOsmBubbleHtml(osmData, false);
        }

        unifiedHtml += '</div>';

        if (hasMatches) {
            unifiedHtml += `<div class="popup-actions"><button class="btn btn-sm btn-secondary" onclick='PopupRenderer.hideMatches(this, ${stop.id}, "${initialViewType}")'>Close Matches</button></div>`;
        } else {
            return '<!-- No matches to display -->';
        }

        return unifiedHtml;
    }

    function generatePopupHtml(stop, initialViewType) {
        const initialContent = generateInitialBubbleHtml(stop, initialViewType);
        let unifiedContent = '';
        if (stop.stop_type === 'matched' && (stop.atlas_matches || stop.osm_matches || (stop.atlas_lat && stop.osm_lat))) {
            unifiedContent = generateUnifiedBubbleHtml(stop, initialViewType);
        }
        const fullHtml = `
            <div class="popup-content-container" data-stop-id="${stop.id}" data-type="${initialViewType}">
                <div class="popup-initial-view" style="display: block;">
                    ${initialContent}
                </div>
                <div class="popup-unified-view" style="display: none;">
                    ${unifiedContent}
                </div>
            </div>
        `;
        return fullHtml;
    }

    function showMatches(buttonElement, stopId) {
        const container = buttonElement.closest('.popup-content-container');
        if (!container) return;

        const initialView = container.querySelector('.popup-initial-view');
        const unifiedView = container.querySelector('.popup-unified-view');
        
        if (initialView) initialView.style.display = 'none';
        if (unifiedView) unifiedView.style.display = 'block';

        const popupElement = container.closest('.leaflet-popup');
        const popupInstance = popupElement && popupElement._leaflet_popup_instance;

        if (popupInstance) {
            // Trigger content update to recalculate width for multiple bubbles
            if (typeof popupInstance._onContentUpdate === 'function') {
                popupInstance._onContentUpdate();
            }
            if (typeof popupInstance._updateLayout === 'function') {
                popupInstance._updateLayout();
            }
            if (typeof popupInstance._updatePosition === 'function') {
                setTimeout(() => {
                    if (typeof popupInstance._updateLayout === 'function') {
                        popupInstance._updateLayout();
                    }
                    popupInstance._updatePosition();
                    if (typeof popupInstance._ensureDragHandleAtTop === 'function') {
                        popupInstance._ensureDragHandleAtTop();
                    }
                }, 0);
            }
        }
    }

    function hideMatches(buttonElement, stopId, initialViewType) {
        const container = buttonElement.closest('.popup-content-container');
        if (!container) return;

        const initialView = container.querySelector('.popup-initial-view');
        const unifiedView = container.querySelector('.popup-unified-view');

        if (unifiedView) unifiedView.style.display = 'none';
        if (initialView) initialView.style.display = 'block';

        const popupElement = container.closest('.leaflet-popup');
        const popupInstance = popupElement && popupElement._leaflet_popup_instance;

        if (popupInstance) {
            // Trigger content update to recalculate width for single bubble view
            if (typeof popupInstance._onContentUpdate === 'function') {
                popupInstance._onContentUpdate();
            }
            if (typeof popupInstance._updatePosition === 'function') {
                setTimeout(() => {
                    if (typeof popupInstance._updateLayout === 'function') {
                        popupInstance._updateLayout();
                    }
                    popupInstance._updatePosition();
                    if (typeof popupInstance._ensureDragHandleAtTop === 'function') {
                        popupInstance._ensureDragHandleAtTop();
                    }
                }, 0);
            }
        }
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


