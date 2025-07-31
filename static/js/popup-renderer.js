(function(global){
    'use strict';

    const PopupRenderer = {};

    const COLLAPSIBLE_DEFAULT_EXPANDED = false;

    /**
     * Generic bubble renderer consolidating previous separate functions.
     *
     * @param {Object} data      – pre-normalised data for the node.
     * @param {Object} opts      – { type:'atlas'|'osm', unmatched:boolean }
     * @returns {String} HTML string for bubble
     */
    function renderBubble(data, opts){
        const { type, unmatched = false } = opts;
        if(!type) throw new Error('PopupRenderer.renderBubble – type is required');

        const isAtlas = type === 'atlas';
        const isOsm   = type === 'osm';

        // Helpers – delegate to utilities where possible
        const link = PopupUtils.createFilterLink;
        const routeHtml = (routesArr, isOsmNodeFlag=false) => {
            // Use PopupUtils collapsible wrapper
            const formatted = PopupUtils.formatRouteList(routesArr);
            return PopupUtils.createCollapsible('Routes', formatted, COLLAPSIBLE_DEFAULT_EXPANDED);
        };

        // Check for mismatch status passed in the data object (for matched stops)
        const isMismatch = data.isOperatorMismatch === true; 
        const mismatchText = isMismatch ? ' <span class="operator-mismatch">(!Operator Mismatch!)</span>' : '';

        // Build table rows based on supplied flags
        const rows = [];
        let routesSection = '';

        if(isAtlas){
            rows.push(['Sloid', unmatched ? data.sloid : link(data.sloid, 'atlas')]);
            if(data.uic_ref){
                rows.push(['UIC Ref', link(data.uic_ref, 'station')]);
            }
            rows.push(['Name', data.atlas_designation_official || 'N/A']);
            rows.push(['Local Ref', data.atlas_designation || 'N/A']);
            // Append mismatch text to Business Org if applicable
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
            // For ATLAS, create separate collapsibles for GTFS and HRDF routes
            const gtfsRoutesHtml = PopupUtils.formatRouteList(data.routes_atlas);
            const hrdfRoutesHtml = PopupUtils.formatHrdfRouteList(data.routes_hrdf);

            routesSection = `
                <div class="route-section">
                    ${PopupUtils.createCollapsible('GTFS Routes', gtfsRoutesHtml, COLLAPSIBLE_DEFAULT_EXPANDED)}
                    ${PopupUtils.createCollapsible('HRDF Routes', hrdfRoutesHtml, COLLAPSIBLE_DEFAULT_EXPANDED)}
                </div>
            `;
        }
        if(isOsm){
            rows.push(['Node ID', unmatched ? data.osm_node_id : link(data.osm_node_id, 'osm')]);
            if(!unmatched){
                if(data.uic_ref) rows.push(['UIC Ref', link(data.uic_ref, 'station')]);
                rows.push(['Name', data.osm_name || 'N/A']);
                if(data.osm_uic_name) rows.push(['UIC Name', data.osm_uic_name]);
                if(data.osm_local_ref) rows.push(['Local Ref', data.osm_local_ref]);
                if(data.osm_network) rows.push(['Network', data.osm_network]);
                 // Append mismatch text to Operator if applicable
                if(data.osm_operator) rows.push(['Operator', data.osm_operator + (isOsm && !unmatched ? mismatchText : '')]);
                
                // Transport type display using osm_node_type
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
                    // Fallback to legacy logic if osm_node_type is not available
                    let transportTypes = [];
                    if (data.osm_amenity === 'ferry_terminal') {
                        transportTypes.push('Ferry Terminal');
                    }
                    if (data.osm_aerialway === 'station') {
                        transportTypes.push('Aerialway Station');
                    }
                    if (data.osm_railway === 'tram_stop') {
                        transportTypes.push('Tram Stop');
                    }
                    if (data.osm_public_transport === 'station') {
                        transportTypes.push('Station');
                    }
                    if (data.osm_public_transport === 'platform') {
                        transportTypes.push('Platform');
                    }
                    if (data.osm_public_transport === 'stop_position') {
                        transportTypes.push('Stop Position');
                    }
                    displayType = transportTypes.length > 0 ? transportTypes.join(', ') : null;
                }
                
                if (displayType) {
                    rows.push(['Type', displayType]);
                }
                
                if(data.osm_lat && data.osm_lon) rows.push(['Coordinates', `(${data.osm_lat}, ${data.osm_lon})`]);
                if(data.distance_m)  rows.push(['Distance', `${parseFloat(data.distance_m).toFixed(1)} m`]);
                rows.push(['Match Type', data.match_type || 'N/A']);
            } else {
                if(data.uic_ref) rows.push(['UIC Ref', link(data.uic_ref, 'station')]);
                rows.push(['Name', data.osm_name || 'N/A']);
                rows.push(['UIC Name', data.osm_uic_name || 'N/A']);
                rows.push(['Network', data.osm_network || 'N/A']);
                rows.push(['Operator', data.osm_operator || 'N/A']); // Mismatch text not added for unmatched OSM
                
                // Transport type display for unmatched OSM using osm_node_type
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
                    // Fallback to legacy logic if osm_node_type is not available
                    let transportTypes = [];
                    if (data.osm_amenity === 'ferry_terminal') {
                        transportTypes.push('Ferry Terminal');
                    }
                    if (data.osm_aerialway === 'station') {
                        transportTypes.push('Aerialway Station');
                    }
                    if (data.osm_railway === 'tram_stop') {
                        transportTypes.push('Tram Stop');
                    }
                    if (data.osm_public_transport === 'station') {
                        transportTypes.push('Station');
                    }
                    if (data.osm_public_transport === 'platform') {
                        transportTypes.push('Platform');
                    }
                    if (data.osm_public_transport === 'stop_position') {
                        transportTypes.push('Stop Position');
                    }
                    displayType = transportTypes.length > 0 ? transportTypes.join(', ') : 'N/A';
                }
                
                rows.push(['Type', displayType]);
                
                rows.push(['Local Ref', data.osm_local_ref || 'N/A']);
            }
             // For OSM, use the single route collapsible as before
             routesSection = `<div class="route-section">${routeHtml(data.routes_osm, isOsm)}</div>`;
        }

        const tableRowsHtml = rows.map(([k,v]) => `<tr><td>${k}:</td><td>${v}</td></tr>`).join('');

        const bubbleClass = isAtlas ? 'atlas-match' : 'osm-match';
        const unmatchedClass = unmatched ? ' unmatched' : '';
        
        // Construct header with optional OSM link
        let headerText = unmatched ? 'Unmatched ' : '';
        let linkHtml = '';
        if (isAtlas) {
            headerText += 'ATLAS Stop';
            // Add link only if uic_ref is present
            if (data.uic_ref) {
                 linkHtml = ` <a href="https://atlas.app.sbb.ch/service-point-directory/service-points/${data.uic_ref}/traffic-point-elements" target="_blank" title="View on SBB ATLAS">(view on ATLAS)</a>`;
            }
        } else if (isOsm) {
            headerText += 'OSM Node';
            // Add link only if osm_node_id is present
            if (data.osm_node_id) {
                 linkHtml = ` <a href="https://www.openstreetmap.org/node/${data.osm_node_id}" target="_blank" title="View on OpenStreetMap">(view on OSM)</a>`;
            }
        }
        const bubbleHeader = `<h5>${headerText}${linkHtml}</h5>`;

        let extraBtns = '';
        if(unmatched){
            if(isAtlas){
                extraBtns = `<button onclick='manualMatchSelect(${data.id}, "atlas")'>Match To</button>`;
            } else if(isOsm){
                extraBtns = `<button onclick='filterByStation(${data.id}, "osm")'>Filter by station</button> <button onclick='manualMatchSelect(${data.id}, "osm")'>Match To</button>`;
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

    /* ------------------------------------------------------------------
     *  Main Popup Generation Functions (moved from main.js)
     * ------------------------------------------------------------------ */

    // HELPER: Generate HTML for a single ATLAS bubble
    function generateSingleAtlasBubbleHtml(data, isUnmatched = false) {
        return renderBubble(data, { type: 'atlas', unmatched: isUnmatched });
    }

    // HELPER: Generate HTML for a single OSM bubble
    function generateSingleOsmBubbleHtml(data, isUnmatched = false) {
        return renderBubble(data, { type: 'osm', unmatched: isUnmatched });
    }

    // FUNCTION: Generate HTML for the initial single-bubble view
    function generateInitialBubbleHtml(stop, initialViewType) {
        let initialHtml = '';
        const isMatched = stop.stop_type === 'matched';
        const isUnmatched = stop.stop_type === 'unmatched' || stop.stop_type === 'osm' || stop.stop_type === 'station'; // Treat osm/station as unmatched for initial view

        if (initialViewType === 'atlas') {
            // For matched ATLAS, create data object matching expected structure for the helper
            const atlasData = {
                id: stop.id,
                sloid: stop.sloid,
                uic_ref: stop.uic_ref,
                atlas_designation: stop.atlas_designation,
                atlas_designation_official: stop.atlas_designation_official,
                atlas_business_org_abbr: stop.atlas_business_org_abbr,
                atlas_lat: stop.atlas_lat,
                atlas_lon: stop.atlas_lon,
                distance_m: stop.distance_m, // Use distance if available (one-to-one case)
                match_type: stop.match_type,
                routes_atlas: stop.routes_atlas,
                stop_type: stop.stop_type, // Pass stop_type for unmatched logic
                isOperatorMismatch: stop.isOperatorMismatch
            };
            initialHtml = generateSingleAtlasBubbleHtml(atlasData, isUnmatched);
        } else if (initialViewType === 'osm') {
            // For matched OSM, create data object matching expected structure
            // If it's an OSM node with multiple ATLAS matches, use its direct data
            // If it's part of an ATLAS stop with multiple OSM matches, find the correct OSM data
            let osmData;
            if (stop.is_osm_node) { // Case: OSM node with multiple ATLAS matches
                osmData = {
                     id: stop.id,
                     osm_node_id: stop.osm_node_id,
                     uic_ref: stop.uic_ref, // May need adjustment depending on data source
                     osm_name: stop.osm_name,
                     osm_uic_name: stop.osm_uic_name,
                     osm_local_ref: stop.osm_local_ref,
                     osm_network: stop.osm_network,
                     osm_operator: stop.osm_operator,
                     osm_public_transport: stop.osm_public_transport,
                     osm_amenity: stop.osm_amenity,
                     osm_aerialway: stop.osm_aerialway,
                     osm_railway: stop.osm_railway,
                     osm_lat: stop.osm_lat,
                     osm_lon: stop.osm_lon,
                     distance_m: null, // Distance isn't directly on the OSM node in this structure
                     match_type: null, // Match type is on the ATLAS links
                     routes_osm: stop.routes_osm,
                     stop_type: stop.stop_type,
                     isOperatorMismatch: stop.isOperatorMismatch
                };
            } else if (Array.isArray(stop.osm_matches)) { // Case: ATLAS stop, find the specific OSM match clicked (This is tricky, we might not know which one was clicked easily)
                // For simplicity, let's assume the 'osm_lat/lon' on the parent 'stop' corresponds to the primary/first match if clicked
                // A better approach would require passing the specific osm_match index/id clicked, but that complicates marker creation.
                // Using the main stop's osm details as a representative for the initial click.
                const representativeOsm = stop.osm_matches[0] || {}; // Fallback to first match or empty
                osmData = {
                     id: representativeOsm.osm_id || stop.id, // Use specific osm_id if possible
                     osm_node_id: representativeOsm.osm_node_id,
                     uic_ref: stop.uic_ref,
                     osm_name: representativeOsm.osm_name || stop.osm_name,
                     osm_uic_name: representativeOsm.osm_uic_name || stop.osm_uic_name,
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
            } else { // Case: One-to-one match or Unmatched OSM
                 osmData = {
                     id: stop.id,
                     osm_node_id: stop.osm_node_id,
                     uic_ref: stop.uic_ref,
                     osm_name: stop.osm_name,
                     osm_uic_name: stop.osm_uic_name,
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

        // Add "See Matches" button if it's a matched stop
        if (isMatched && (stop.atlas_matches || stop.osm_matches || (stop.atlas_lat && stop.osm_lat))) {
            initialHtml += `<div class="popup-actions"><button class="btn btn-sm btn-secondary" onclick='PopupRenderer.showMatches(this, ${stop.id})'>See Matches</button></div>`;
        }
        
        return initialHtml;
    }

    // FUNCTION: Generate HTML for the unified multi-bubble view
    function generateUnifiedBubbleHtml(stop, initialViewType) {
        // This function reconstructs the logic from the old createUnifiedPopupContent
        let unifiedHtml = '<div class="matches-container">';
        let hasMatches = false;

        // Case: OSM-centric view (OSM node with multiple ATLAS matches)
        if (stop.stop_type === 'matched' && stop.is_osm_node && Array.isArray(stop.atlas_matches)) {
            hasMatches = true;
            // OSM bubble first
            const osmData = { ...stop, uic_ref: stop.uic_ref }; // Ensure UIC ref is included
            unifiedHtml += generateSingleOsmBubbleHtml(osmData, false);
            // Then ATLAS match bubbles
            stop.atlas_matches.forEach((atlasMatch, index) => {
                // Construct the data object needed for the helper
                const atlasData = {
                     ...atlasMatch, // Includes sloid, names, coords, distance, match_type, routes_atlas
                     id: stop.id, // Reference the main stop ID for potential actions if needed
                     uic_ref: atlasMatch.uic_ref // Use the specific UIC ref from the match if available
                };
                unifiedHtml += generateSingleAtlasBubbleHtml(atlasData, false);
            });
        }
        // Case: ATLAS-centric view (ATLAS stop with multiple OSM matches)
        else if (stop.stop_type === 'matched' && Array.isArray(stop.osm_matches)) {
            hasMatches = true;
            // ATLAS bubble first
            const atlasData = { ...stop }; // Pass the main stop object
            unifiedHtml += generateSingleAtlasBubbleHtml(atlasData, false);
            // Then OSM match bubbles
            stop.osm_matches.forEach((osmMatch, index) => {
                 // Construct the data object needed for the helper
                const osmData = {
                     ...osmMatch, // Includes node_id, names, coords, distance, routes_osm, match_type
                     id: osmMatch.osm_id || stop.id, // Use specific osm_id if possible
                     uic_ref: stop.uic_ref // Use the parent ATLAS stop's UIC ref
                };
                unifiedHtml += generateSingleOsmBubbleHtml(osmData, false);
            });
        }
        // Case: Simple one-to-one matched stop (when stop object is flat after format_stop_data)
        else if (stop.stop_type === 'matched' && stop.atlas_lat && stop.osm_lat) {
            hasMatches = true;
            // ATLAS data part
            const atlasData = {
                id: stop.id, // Use the main ID
                sloid: stop.sloid,
                uic_ref: stop.uic_ref,
                atlas_designation: stop.atlas_designation,
                atlas_designation_official: stop.atlas_designation_official,
                atlas_business_org_abbr: stop.atlas_business_org_abbr,
                atlas_lat: stop.atlas_lat,
                atlas_lon: stop.atlas_lon,
                distance_m: stop.distance_m, 
                match_type: stop.match_type,
                routes_atlas: stop.routes_atlas,
                isOperatorMismatch: stop.isOperatorMismatch // Pass through mismatch status
            };
            unifiedHtml += generateSingleAtlasBubbleHtml(atlasData, false);

            // OSM data part
            const osmData = {
                id: stop.id, // Use the main ID, or a specific osm_db_id if available and different
                osm_node_id: stop.osm_node_id,
                uic_ref: stop.uic_ref, // Often shared or derived
                osm_name: stop.osm_name,
                osm_uic_name: stop.osm_uic_name,
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
                isOperatorMismatch: stop.isOperatorMismatch // Pass through mismatch status
            };
            unifiedHtml += generateSingleOsmBubbleHtml(osmData, false);
        }

        unifiedHtml += '</div>'; // Close matches-container

        // Add "Close Matches" button if matches were displayed
        if (hasMatches) {
            unifiedHtml += `<div class="popup-actions"><button class="btn btn-sm btn-secondary" onclick='PopupRenderer.hideMatches(this, ${stop.id}, "${initialViewType}")'>Close Matches</button></div>`;
        } else {
            // If somehow called for an unmatched stop, return an empty string or error message
            return '<!-- No matches to display -->';
        }

        return unifiedHtml;
    }

    // Assemble the full popup HTML with initial and unified views
    function generatePopupHtml(stop, initialViewType) {
        const initialContent = generateInitialBubbleHtml(stop, initialViewType);
        let unifiedContent = '';
        // Only generate unified content if the stop is matched
        if (stop.stop_type === 'matched' && (stop.atlas_matches || stop.osm_matches || (stop.atlas_lat && stop.osm_lat))) {
            unifiedContent = generateUnifiedBubbleHtml(stop, initialViewType);
        }

        // Note: The drag handle is added by move_popup.js inside the wrapper,
        // so this container will sit *inside* the content node managed by Leaflet/DraggablePopup.
        const fullHtml = `
            <div class="popup-content-container" data-stop-id="${stop.id}">
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

    // Show the unified matches view
    function showMatches(buttonElement, stopId) {
        const container = buttonElement.closest('.popup-content-container');
        if (!container) return;

        const initialView = container.querySelector('.popup-initial-view');
        const unifiedView = container.querySelector('.popup-unified-view');
        
        // Toggle views
        if (initialView) initialView.style.display = 'none';
        if (unifiedView) unifiedView.style.display = 'block';

        // Find the Leaflet popup instance (set by move_popup.js)
        const popupElement = container.closest('.leaflet-popup');
        const popupInstance = popupElement && popupElement._leaflet_popup_instance;

        if (popupInstance) {
            // Force Leaflet to recalculate the popup's layout so that the new
            // (larger) unified view isn't clipped. This avoids the situation
            // where only the first match bubble is visible without scrolling.
            if (typeof popupInstance._updateLayout === 'function') {
                popupInstance._updateLayout();
            }
            if (typeof popupInstance._updatePosition === 'function') {
                // Use setTimeout to allow the DOM to update before recalculating position
                setTimeout(() => {
                    if (typeof popupInstance._updateLayout === 'function') {
                        popupInstance._updateLayout();
                    }
                    popupInstance._updatePosition();
                    // Ensure drag-handle stays at the top after the layout change
                    if (typeof popupInstance._ensureDragHandleAtTop === 'function') {
                        popupInstance._ensureDragHandleAtTop();
                    }
                }, 0);
            }
        }
    }

    // Hide the unified matches view, return to initial
    function hideMatches(buttonElement, stopId, initialViewType) {
        const container = buttonElement.closest('.popup-content-container');
        if (!container) return;

        const initialView = container.querySelector('.popup-initial-view');
        const unifiedView = container.querySelector('.popup-unified-view');

        // Toggle views
        if (unifiedView) unifiedView.style.display = 'none';
        if (initialView) initialView.style.display = 'block';

        // Find the Leaflet popup instance
        const popupElement = container.closest('.leaflet-popup');
        const popupInstance = popupElement && popupElement._leaflet_popup_instance;

        if (popupInstance) {
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