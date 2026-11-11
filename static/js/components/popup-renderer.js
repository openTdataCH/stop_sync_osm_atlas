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

    // 7 decimals (about 1 cm), as OSM stores them, so every source has the same precision.
    function formatCoordinate(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? String(Number(parsed.toFixed(7))) : String(value);
    }

    function formatCoords(lat, lon) {
        if (!hasValue(lat) || !hasValue(lon)) return null;
        return `(${formatCoordinate(lat)}, ${formatCoordinate(lon)})`;
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

    const TWO_SIDED_STOP_DOC_URL = '/docs/reference_matching#two-sided-stops-two_sided_stop';

    // The section of the docs that explains the rule behind a match type. Identifier,
    // two-sided stop and reference types start with the profile's namespace, such as uic_.
    function getMatchDocUrl(matchType) {
        if (!matchType) return null;
        const mt = String(matchType).toLowerCase();
        if (/_group_(long_)?distance$/.test(mt)) return '/docs/distance_matching#group-distance-rules-group_distance-and-group_long_distance';
        if (mt === 'local_ref_distance') return '/docs/distance_matching#local_ref-distance-rule-local_ref_distance';
        if (mt.startsWith('distance_')) return '/docs/distance_matching#nearest-candidate-rules';
        if (mt.endsWith('_identifier')) return '/docs/reference_matching#identifier-matching-identifier';
        if (mt.endsWith('_two_sided_stop')) return TWO_SIDED_STOP_DOC_URL;
        if (mt.includes('_reference_')) return '/docs/reference_matching#how-the-reference-rule-works';
        if (mt.startsWith('name_')) return '/docs/name_matching';
        if (mt.startsWith('gtfs_')) return '/docs/gtfs_route_matching';
        return null;
    }

    function withMatchDocLink(text, docUrl) {
        if (!docUrl) return text;
        return `${text} <a href="${docUrl}" class="doc-link" target="_blank" rel="noopener" title="What this matching rule does"><i class="fas fa-info-circle" aria-hidden="true"></i></a>`;
    }

    function buildMatchTypeHtml(matchType) {
        const text = matchType || 'N/A';
        return withMatchDocLink(text, getMatchDocUrl(text));
    }

    // An effectively matched element is the middle of a two-sided stop whose sides are
    // matched. It has no match of its own, so no match type: its stop type names it.
    function buildOsmMatchTypeHtml(data) {
        if (data.stop_type === 'effectively_matched') {
            return withMatchDocLink('Middle of a matched two-sided stop', TWO_SIDED_STOP_DOC_URL);
        }
        return buildMatchTypeHtml(data.match_type);
    }

    function buildFilterText(value, type, options, displayText) {
        if (!hasValue(value)) return 'N/A';
        return PopupUtils.createFilterLink(value, type, displayText, {
            enableFilterLink: !(options && options.enableFilterLinks === false)
        });
    }

    function getBubbleClass(type) {
        if (type === 'atlas') return 'atlas-match';
        if (type === 'osm') return 'osm-match';
        return 'gtfs-match';
    }

    function buildPopupTableRowsHtml(rows) {
        if (!Array.isArray(rows) || rows.length === 0) return '';
        return `<table class="popup-table">${rows.map(([label, value]) => `<tr><td>${label}:</td><td>${value}</td></tr>`).join('')}</table>`;
    }

    function buildSeeMatchesButtonHtml(matchCount = 1) {
        const label = matchCount > 1 ? `See Matches (${matchCount})` : 'See Matches';
        return `<button type="button" class="btn btn-sm popup-action-btn" onclick="PopupRenderer.showMatches(this)">${label}</button>`;
    }

    // The bar at the top of every matches view; it returns to the stop's card.
    function buildMatchesBarHtml() {
        return `
            <div class="popup-view-bar">
                <button type="button" class="popup-view-back" onclick="PopupRenderer.hideMatches(this)"><i class="fas fa-chevron-left" aria-hidden="true"></i> Close Matches</button>
            </div>`;
    }

    function formatPopupMono(value) {
        return `<span class="popup-mono">${value || 'N/A'}</span>`;
    }

    function appendIndividualMatchMetadataRows(rows, data, matchFieldName = 'match_method') {
        if (hasValue(data && data[matchFieldName])) {
            rows.push(['Mapping Method', buildMatchTypeHtml(data[matchFieldName])]);
        }

        const distance = formatDistanceMeters(data && data.distance_m);
        if (distance) {
            rows.push(['Distance', distance]);
        }

        return rows;
    }

    function collectMappingMethods(items) {
        if (!Array.isArray(items) || items.length === 0) {
            return [];
        }

        const seen = new Set();
        return items.reduce(function (methods, item) {
            const matchMethod = item && hasValue(item.match_method)
                ? String(item.match_method).trim()
                : '';
            if (!matchMethod || seen.has(matchMethod)) {
                return methods;
            }
            seen.add(matchMethod);
            methods.push(matchMethod);
            return methods;
        }, []);
    }

    function buildMappingMethodRow(items) {
        const methods = collectMappingMethods(items);
        if (methods.length === 0) {
            return null;
        }

        return [
            methods.length === 1 ? 'Mapping Method' : 'Mapping Methods',
            methods.map(buildMatchTypeHtml).join(', ')
        ];
    }

    // The Index page turns this into a permalink; the raw id keeps the
    // URL format in one place (Permalinks.stopParams).
    function buildCopyLinkButtonHtml(type, ref) {
        const safeRef = SharedUtils.escapeHtml(ref).replace(/"/g, '&quot;');
        return `<button type="button" class="popup-copy-link" data-permalink-type="${type}" data-permalink-ref="${safeRef}" title="Copy a link that opens the map on this stop"><i class="fas fa-link"></i> Copy link</button>`;
    }

    function renderBubbleCard(options) {
        const {
            type,
            unmatched = false,
            headerHtml,
            rows = [],
            sectionsHtml = '',
            footerHtml = '',
            osmEditorUrl = null,
            permalinkRef = null,
            mainMapUrl = null,
        } = options;

        const bubbleClass = getBubbleClass(type);
        const unmatchedClass = unmatched ? ' unmatched' : '';
        const links = [];
        if (type === 'osm' && osmEditorUrl) {
            links.push(`<a href="${osmEditorUrl}" class="osm-editor-link" target="_blank" rel="noopener noreferrer"><i class="fas fa-external-link-alt"></i> Edit in OSM iD Editor</a>`);
        }
        if (hasValue(permalinkRef)) links.push(buildCopyLinkButtonHtml(type, permalinkRef));
        if (hasValue(mainMapUrl)) {
            const safeUrl = SharedUtils.escapeHtml(mainMapUrl).replace(/"/g, '&quot;');
            links.push(`<a href="${safeUrl}" class="popup-main-map-link" target="_blank" rel="noopener" title="Open the main map on this stop in a new tab"><i class="fas fa-map-marked-alt"></i> Open in main map</a>`);
        }
        const osmEditorLinkHtml = links.length
            ? `<div class="osm-editor-link-container mt-2">${links.join('')}</div>`
            : '';

        return `
            <div class="${bubbleClass}${unmatchedClass}">
                <div class="bubble-body">
                    ${headerHtml}
                    ${buildPopupTableRowsHtml(rows)}
                    ${osmEditorLinkHtml}
                    ${sectionsHtml}
                    ${footerHtml}
                </div>
            </div>`;
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
        const disused = type === 'osm' && data.stop_type === 'osm_disused';
        let headerText = disused ? 'Disused ' : (unmatched ? 'Unmatched ' : '');
        let linkHtml = '';

        if (type === 'atlas') {
            const label = SharedUtils.sourceLabelHtml();
            headerText += `${label} Stop`;
            const sourceUrl = SharedUtils.sourceUrl(data);
            if (sourceUrl) {
                linkHtml = ` <a href="${SharedUtils.escapeHtml(sourceUrl).replace(/"/g, '&quot;')}" target="_blank" rel="noopener noreferrer">(view on ${label})</a>`;
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

    function buildGtfsBubbleHeader(unmatched) {
        return `<h5>${unmatched ? 'Unmatched ' : ''}GTFS Stop</h5>`;
    }

    function buildOsmTagsTable(tags) {
        const keys = tags && typeof tags === 'object' ? Object.keys(tags).sort() : [];
        if (keys.length === 0) return null;
        const rows = keys.map(key => `<tr><td>${SharedUtils.escapeHtml(key)}</td><td>${SharedUtils.escapeHtml(String(tags[key]))}</td></tr>`).join('');
        return { count: keys.length, html: `<table class="popup-osm-tags">${rows}</table>` };
    }

    function buildOsmTagsCollapsible(tags) {
        const table = buildOsmTagsTable(tags);
        return table ? PopupUtils.createCollapsible(`OSM tags (${table.count})`, table.html, false) : null;
    }

    function buildBubbleCollapsibles(data, type, hideRoutesAndNotes, options = {}) {
        const collapsibles = [];
        if (!hideRoutesAndNotes && SharedUtils.hasCapability('routes')) {
            const routes = type === 'atlas' ? data.routes_gtfs : data.routes_osm;
            const formattedRoutes = type === 'atlas'
                ? PopupUtils.formatAtlasRouteList(routes, { enableRouteLink: !(options.enableRouteLinks === false) })
                : PopupUtils.formatRouteList(routes, { enableRouteLink: !(options.enableRouteLinks === false) });
            collapsibles.push(PopupUtils.createCollapsible('Routes', formattedRoutes, COLLAPSIBLE_DEFAULT_EXPANDED));
        }
        // Single-stop endpoints send every OSM tag; list payloads do not.
        const tags = !hideRoutesAndNotes && type === 'osm' ? buildOsmTagsCollapsible(data.osm_tags) : null;
        if (tags) collapsibles.push(tags);
        return collapsibles;
    }

    function buildBubbleFooterHtml(data, type, unmatched, hideRoutesAndNotes, actionButtonHtml, options = {}) {
        const collapsibles = buildBubbleCollapsibles(data, type, hideRoutesAndNotes, options);
        const buttons = collapsibles.map(collapsible => collapsible.buttonHtml || '').join('') + (actionButtonHtml || '');
        const panels = collapsibles.map(collapsible => collapsible.panelHtml || '').join('');
        if (!buttons && !panels) return '';

        return `
            <div class="bubble-footer">
                ${buttons ? `<div class="bubble-btn-row">${buttons}</div>` : ''}
                ${panels}
            </div>`;
    }

    function buildAtlasRows(data, unmatched, options = {}) {
        const rows = [];
        const mismatchText = data.isOperatorMismatch && !unmatched
            ? ' <span class="operator-mismatch">(!Operator Mismatch!)</span>'
            : '';

        rows.push([SharedUtils.sourceIdLabelHtml(), unmatched ? (data.sloid || 'N/A') : buildFilterText(data.sloid, 'atlas', options)]);
        if (hasValue(data.uic_ref)) rows.push(['UIC Ref', buildFilterText(data.uic_ref, 'station', options)]);
        rows.push(['Name', data.atlas_designation_official || 'N/A']);
        rows.push(['Designation', data.atlas_designation || 'N/A']);
        rows.push(['Business Org', `${data.atlas_business_org_abbr || 'N/A'}${mismatchText}`]);

        const coords = formatCoords(data.atlas_lat, data.atlas_lon);
        if (coords) rows.push(['Coord', coords]);

        if (!unmatched && !options.hideMatchMetadata) {
            const distance = formatDistanceMeters(data.distance_m);
            if (distance) rows.push(['Distance', distance]);
            rows.push(['Match Type', buildMatchTypeHtml(data.match_type)]);
        }

        return rows;
    }

    function buildOsmRows(data, unmatched, options = {}) {
        const rows = [];
        const mismatchText = data.isOperatorMismatch && !unmatched
            ? ' <span class="operator-mismatch">(!Operator Mismatch!)</span>'
            : '';

        rows.push(['Node ID', unmatched ? (data.osm_node_id || 'N/A') : buildFilterText(data.osm_node_id, 'osm', options)]);
        if (hasValue(data.osm_lifecycle)) {
            rows.push(['Status', `Out of service in OSM (<code>${SharedUtils.escapeHtml(data.osm_lifecycle)}:</code> prefix); never matched`]);
        }

        if (unmatched) {
            if (hasValue(data.uic_ref)) rows.push(['UIC Ref', buildFilterText(data.uic_ref, 'station', options)]);
            if (hasValue(data.osm_uic_ref)) rows.push(['OSM UIC Ref', data.osm_uic_ref]);
            rows.push(['Name', data.osm_name || 'N/A']);
            rows.push(['UIC Name', data.osm_uic_name || 'N/A']);
            rows.push(['Network', data.osm_network || 'N/A']);
            rows.push(['Operator', data.osm_operator || 'N/A']);
            if (hasValue(data.osm_operator_wikidata)) rows.push(['Operator Wikidata', data.osm_operator_wikidata]);
            if (hasValue(data.osm_network_wikidata)) rows.push(['Network Wikidata', data.osm_network_wikidata]);
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
        if (hasValue(data.osm_operator_wikidata)) rows.push(['Operator Wikidata', data.osm_operator_wikidata]);
        if (hasValue(data.osm_network_wikidata)) rows.push(['Network Wikidata', data.osm_network_wikidata]);

        const osmType = getOsmTypeDisplay(data, false);
        if (osmType) rows.push(['Type', osmType]);

        const coords = formatCoords(data.osm_lat, data.osm_lon);
        if (coords) rows.push(['Coord', coords]);

        if (!options.hideMatchMetadata) {
            const distance = formatDistanceMeters(data.distance_m);
            if (distance) rows.push(['Distance', distance]);
            rows.push(['Match Type', buildOsmMatchTypeHtml(data)]);
        }
        return rows;
    }

    function renderBubble(data, opts) {
        const { type, unmatched = false, hideRoutesAndNotes = false, actionButtonHtml = '' } = opts;
        if (!type) throw new Error('PopupRenderer.renderBubble - type is required');

        const bubbleHeader = buildBubbleHeader(data, type, unmatched);
        const rows = type === 'atlas'
            ? buildAtlasRows(data, unmatched, opts)
            : buildOsmRows(data, unmatched, opts);
        const footerHtml = buildBubbleFooterHtml(data, type, unmatched, hideRoutesAndNotes, actionButtonHtml, opts);

        return renderBubbleCard({
            type,
            unmatched,
            headerHtml: bubbleHeader,
            rows,
            footerHtml,
            osmEditorUrl: type === 'osm' ? buildOsmEditorUrl(data.osm_node_id) : null,
            permalinkRef: opts.permalinks ? (type === 'atlas' ? data.sloid : data.osm_node_id) : null,
            // Pages without the main map's own popups link to it instead.
            mainMapUrl: typeof opts.mainMapUrl === 'function'
                ? opts.mainMapUrl(type, type === 'atlas' ? data.sloid : data.osm_node_id) : null,
        });
    }

    function wrapSingleBubble(innerHtml, type, stopId) {
        return `<div class="popup-content-container" data-stop-id="${stopId}" data-type="${type}">${innerHtml}</div>`;
    }

    function wrapPopupViews(initialContent, unifiedContent, type, stopId) {
        if (!unifiedContent) {
            return wrapSingleBubble(initialContent, type, stopId);
        }

        return `
            <div class="popup-content-container popup-outer-wrapper" data-stop-id="${stopId}" data-type="${type}">
                <div class="popup-initial-view" style="display: block;">
                    ${initialContent}
                </div>
                <div class="popup-unified-view" style="display: none;">
                    ${unifiedContent}
                </div>
            </div>`;
    }

    function buildUnifiedPopupViewHtml(cardsHtml) {
        return `${buildMatchesBarHtml()}<div class="matches-container">${cardsHtml}</div>`;
    }

    function wrapPopupMatchCard(cardHtml) {
        return `<div class="popup-match-item">${cardHtml}</div>`;
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
            routes_gtfs: stop.routes_gtfs,
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
                osm_operator_wikidata: stop.osm_operator_wikidata,
                osm_network_wikidata: stop.osm_network_wikidata,
                osm_public_transport: stop.osm_public_transport,
                osm_amenity: stop.osm_amenity,
                osm_aerialway: stop.osm_aerialway,
                osm_railway: stop.osm_railway,
                osm_lat: stop.osm_lat,
                osm_lon: stop.osm_lon,
                distance_m: firstAtlas ? firstAtlas.distance_m : stop.distance_m,
                match_type: stop.match_type || (firstAtlas ? firstAtlas.match_type : null),
                routes_osm: stop.routes_osm,
                osm_tags: stop.osm_tags,
                osm_lifecycle: stop.osm_lifecycle,
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
                osm_operator_wikidata: representative.osm_operator_wikidata || stop.osm_operator_wikidata,
                osm_network_wikidata: representative.osm_network_wikidata || stop.osm_network_wikidata,
                osm_public_transport: representative.osm_public_transport || stop.osm_public_transport,
                osm_amenity: representative.osm_amenity || stop.osm_amenity,
                osm_aerialway: representative.osm_aerialway || stop.osm_aerialway,
                osm_railway: representative.osm_railway || stop.osm_railway,
                osm_lat: representative.osm_lat || stop.osm_lat,
                osm_lon: representative.osm_lon || stop.osm_lon,
                distance_m: representative.distance_m || stop.distance_m,
                match_type: representative.match_type || stop.match_type,
                routes_osm: representative.routes_osm || stop.routes_osm,
                osm_tags: representative.osm_tags || stop.osm_tags,
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
            osm_operator_wikidata: stop.osm_operator_wikidata,
            osm_network_wikidata: stop.osm_network_wikidata,
            osm_public_transport: stop.osm_public_transport,
            osm_amenity: stop.osm_amenity,
            osm_aerialway: stop.osm_aerialway,
            osm_railway: stop.osm_railway,
            osm_lat: stop.osm_lat,
            osm_lon: stop.osm_lon,
            distance_m: stop.distance_m,
            match_type: stop.match_type,
            routes_osm: stop.routes_osm,
            osm_tags: stop.osm_tags,
            osm_lifecycle: stop.osm_lifecycle,
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

    function buildAtlasReferenceRows(data, unmatched, options = {}) {
        const rows = buildAtlasRows(data, unmatched, {
            ...options,
            hideMatchMetadata: true,
        });

        const mappingMethodRow = buildMappingMethodRow(data.matched_gtfs);
        if (mappingMethodRow) {
            rows.push(mappingMethodRow);
        }
        rows.push(['Matched GTFS', String(data.matched_gtfs_count || 0)]);
        rows.push(['Same-UIC GTFS', String(data.same_uic_gtfs_count || 0)]);
        return rows;
    }

    function buildAtlasReferenceMatchRows(data, options = {}) {
        const rows = buildAtlasRows(data, false, {
            ...options,
            hideMatchMetadata: true,
        });
        return appendIndividualMatchMetadataRows(rows, data);
    }

    function buildGtfsRows(data, options = {}) {
        const rows = [
            ['stop_id', formatPopupMono(data.stop_id)],
            ['Name', data.stop_name || 'N/A'],
            ['UIC', formatPopupMono(data.uic_number)],
            ['local_ref', formatPopupMono(data.local_ref)],
            ['Normalized', formatPopupMono(data.normalized_local_ref)],
        ];

        const coords = formatCoords(data.stop_lat, data.stop_lon);
        if (coords) {
            rows.push(['Coord', coords]);
        }

        if (options.includeSummaryCounts) {
            const mappingMethodRow = buildMappingMethodRow(data.matched_sloids);
            if (mappingMethodRow) {
                rows.push(mappingMethodRow);
            }
            rows.push(['Matched SLOIDs', String(data.matched_sloid_count || 0)]);
            rows.push(['ATLAS Candidates', String(data.candidate_atlas_count || 0)]);
        }

        if (options.includeMatchMetadata) {
            appendIndividualMatchMetadataRows(rows, data);
        }

        return rows;
    }

    function buildGtfsReferenceRows(data) {
        return buildGtfsRows(data, { includeSummaryCounts: true });
    }

    function buildGtfsReferenceMatchRows(data) {
        return buildGtfsRows(data, { includeMatchMetadata: true });
    }

    function gtfsReferenceHasMatches(data) {
        return Number(data && data.matched_sloid_count || 0) > 0;
    }

    function atlasReferenceHasMatches(data) {
        return Number(data && data.matched_gtfs_count || 0) > 0;
    }

    function renderAtlasReferenceSummaryBubbleHtml(data, options = {}) {
        const unmatched = Number(data.matched_gtfs_count || 0) === 0;
        const actionButtonHtml = !options.suppressMatchToggle && atlasReferenceHasMatches(data)
            ? buildSeeMatchesButtonHtml()
            : '';

        return renderBubbleCard({
            type: 'atlas',
            unmatched,
            headerHtml: buildBubbleHeader(data, 'atlas', unmatched),
            rows: buildAtlasReferenceRows(data, unmatched, options),
            footerHtml: buildBubbleFooterHtml(data, 'atlas', unmatched, false, actionButtonHtml, options),
            permalinkRef: options.permalinks ? data.sloid : null,
        });
    }

    function renderAtlasReferenceMatchBubbleHtml(data, options = {}) {
        return renderBubbleCard({
            type: 'atlas',
            unmatched: false,
            headerHtml: buildBubbleHeader(data, 'atlas', false),
            rows: buildAtlasReferenceMatchRows(data, options),
            footerHtml: buildBubbleFooterHtml(data, 'atlas', false, false, '', options),
            permalinkRef: options.permalinks ? data.sloid : null,
        });
    }

    function renderGtfsReferenceSummaryBubbleHtml(data, options = {}) {
        const unmatched = Number(data.matched_sloid_count || 0) === 0;
        const actionButtonHtml = !options.suppressMatchToggle && gtfsReferenceHasMatches(data)
            ? buildSeeMatchesButtonHtml()
            : '';

        return renderBubbleCard({
            type: 'gtfs',
            unmatched,
            headerHtml: buildGtfsBubbleHeader(unmatched),
            rows: buildGtfsReferenceRows(data),
            // OpenTransportData GTFS is the source behind ATLAS itineraries,
            // so its route payload uses the same routes_gtfs contract.
            footerHtml: buildBubbleFooterHtml(data, 'atlas', unmatched, false, actionButtonHtml, options),
            permalinkRef: options.permalinks ? data.stop_id : null,
        });
    }

    function renderGtfsReferenceMatchBubbleHtml(data, options = {}) {
        return renderBubbleCard({
            type: 'gtfs',
            unmatched: false,
            headerHtml: buildGtfsBubbleHeader(false),
            rows: buildGtfsReferenceMatchRows(data),
            footerHtml: buildBubbleFooterHtml(data, 'atlas', false, false, '', options),
            permalinkRef: options.permalinks ? data.stop_id : null,
        });
    }

    function buildGtfsReferenceUnifiedBubbleHtml(data, options = {}) {
        if (!gtfsReferenceHasMatches(data)) {
            return '';
        }

        const cardsHtml = [
            wrapPopupMatchCard(renderGtfsReferenceSummaryBubbleHtml({
                ...data,
                matched_sloid_count: data.matched_sloid_count,
                candidate_atlas_count: data.candidate_atlas_count,
            }, { ...options, suppressMatchToggle: true })),
            ...(Array.isArray(data.matched_sloids) ? data.matched_sloids.map(function (item) {
                return wrapPopupMatchCard(renderAtlasReferenceMatchBubbleHtml(item, options));
            }) : [])
        ].join('');

        return buildUnifiedPopupViewHtml(cardsHtml);
    }

    function buildAtlasReferenceUnifiedBubbleHtml(data, options = {}) {
        if (!atlasReferenceHasMatches(data)) {
            return '';
        }

        const cardsHtml = [
            wrapPopupMatchCard(renderAtlasReferenceSummaryBubbleHtml({
                ...data,
                matched_gtfs_count: data.matched_gtfs_count,
                same_uic_gtfs_count: data.same_uic_gtfs_count,
            }, { ...options, suppressMatchToggle: true })),
            ...(Array.isArray(data.matched_gtfs) ? data.matched_gtfs.map(function (item) {
                return wrapPopupMatchCard(renderGtfsReferenceMatchBubbleHtml(item, options));
            }) : [])
        ].join('');

        return buildUnifiedPopupViewHtml(cardsHtml);
    }

    function generateAtlasReferenceBubbleHtml(data, options = {}) {
        const content = renderAtlasReferenceSummaryBubbleHtml(data, options);
        const unifiedContent = buildAtlasReferenceUnifiedBubbleHtml(data, options);

        return wrapPopupViews(content, unifiedContent, 'atlas', data && (data.sloid || data.id || ''));
    }

    function generateGtfsReferenceBubbleHtml(data, options = {}) {
        const content = renderGtfsReferenceSummaryBubbleHtml(data, options);
        const unifiedContent = buildGtfsReferenceUnifiedBubbleHtml(data, options);

        return wrapPopupViews(content, unifiedContent, 'gtfs', data && (data.stop_id || data.id || ''));
    }

    function generateGtfsStopIdSloidPopupHtml(data, options = {}) {
        if (!data || !data.entity_type) {
            throw new Error('PopupRenderer.generateGtfsStopIdSloidPopupHtml - entity_type is required');
        }

        if (data.entity_type === 'atlas') {
            return generateAtlasReferenceBubbleHtml(data, {
                ...options,
                enableFilterLinks: false,
                enableRouteLinks: false,
            });
        }

        if (data.entity_type === 'gtfs') {
            return generateGtfsReferenceBubbleHtml(data, options);
        }

        throw new Error(`PopupRenderer.generateGtfsStopIdSloidPopupHtml - unsupported entity_type: ${data.entity_type}`);
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
        const isUnmatched = ['atlas_unmatched', 'osm_unmatched', 'osm_disused'].includes(stop.stop_type);
        const actionButtonHtml = stopHasMatches(stop)
            ? buildSeeMatchesButtonHtml(buildMatchPairs(stop).length)
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

    // One ATLAS | OSM pair per match of the stop. Distance and match type belong
    // to the pair, so they come from the matched counterpart.
    function buildMatchPairs(stop) {
        const [primary, ...counterparts] = buildUnifiedBubbleSpecs(stop);
        if (!primary) return [];
        return counterparts
            .filter(counterpart => counterpart.type !== primary.type)
            .map(counterpart => ({
                atlas: primary.type === 'atlas' ? primary.data : counterpart.data,
                osm: primary.type === 'osm' ? primary.data : counterpart.data,
                distance_m: hasValue(counterpart.data.distance_m) ? counterpart.data.distance_m : primary.data.distance_m,
                match_type: counterpart.data.match_type || primary.data.match_type,
            }));
    }

    function compareSourceHeadHtml(type, data) {
        const label = type === 'atlas' ? SharedUtils.sourceLabelHtml() : 'OSM';
        const url = type === 'atlas'
            ? SharedUtils.sourceUrl(data)
            : (hasValue(data.osm_node_id) ? buildOsmBrowseUrl(data.osm_node_id) : null);
        if (!url) return label;
        const safeUrl = SharedUtils.escapeHtml(url).replace(/"/g, '&quot;');
        const site = type === 'atlas' ? label : 'OpenStreetMap';
        return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" title="View on ${site}">${label} <i class="fas fa-external-link-alt"></i></a>`;
    }

    function escapeText(value) {
        return hasValue(value) ? SharedUtils.escapeHtml(String(value)) : null;
    }

    function sameText(left, right) {
        return String(left).trim().toLowerCase() === String(right).trim().toLowerCase();
    }

    // The fields both sources describe, side by side. Fields only OSM has (UIC name,
    // network, Wikidata, type) are in the pair's Tags panel.
    function buildCompareRows(atlas, osm, options) {
        const differ = (left, right) => hasValue(left) && hasValue(right) && !sameText(left, right);
        return [
            { label: 'ID', atlas: buildFilterText(atlas.sloid, 'atlas', options), osm: buildFilterText(osm.osm_node_id, 'osm', options) },
            {
                label: 'UIC Ref',
                atlas: hasValue(atlas.uic_ref) ? buildFilterText(atlas.uic_ref, 'station', options) : null,
                osm: escapeText(osm.osm_uic_ref),
                differs: differ(atlas.uic_ref, osm.osm_uic_ref),
            },
            { label: 'Name', atlas: escapeText(atlas.atlas_designation_official), osm: escapeText(osm.osm_name) },
            {
                label: 'Platform',
                atlas: escapeText(atlas.atlas_designation),
                osm: escapeText(osm.osm_local_ref),
                differs: differ(atlas.atlas_designation, osm.osm_local_ref),
            },
            {
                label: 'Operator',
                atlas: escapeText(atlas.atlas_business_org_abbr),
                osm: escapeText(osm.osm_operator),
                differs: Boolean(atlas.isOperatorMismatch || osm.isOperatorMismatch),
            },
            { label: 'Coord', atlas: formatCoords(atlas.atlas_lat, atlas.atlas_lon), osm: formatCoords(osm.osm_lat, osm.osm_lon) },
        ].filter(row => hasValue(row.atlas) || hasValue(row.osm));
    }

    function compareLinksHtml(type, data, options) {
        const ref = type === 'atlas' ? data.sloid : data.osm_node_id;
        const links = [];
        if (type === 'osm') {
            const editorUrl = buildOsmEditorUrl(data.osm_node_id);
            if (editorUrl) links.push(`<a href="${editorUrl}" class="osm-editor-link" target="_blank" rel="noopener noreferrer" title="Edit in the OSM iD editor"><i class="fas fa-external-link-alt"></i> iD editor</a>`);
        }
        if (options.permalinks && hasValue(ref)) links.push(buildCopyLinkButtonHtml(type, ref));
        if (typeof options.mainMapUrl === 'function') {
            const url = options.mainMapUrl(type, ref);
            if (hasValue(url)) {
                const safeUrl = SharedUtils.escapeHtml(url).replace(/"/g, '&quot;');
                links.push(`<a href="${safeUrl}" class="popup-main-map-link" target="_blank" rel="noopener" title="Open the main map on this stop in a new tab"><i class="fas fa-map-marked-alt"></i> Main map</a>`);
            }
        }
        return links.map(link => `<div class="popup-compare-link">${link}</div>`).join('');
    }

    let detailPanelCount = 0;

    // Routes and tags of a pair behind tabs named by their source; one panel is
    // open at a time, so it is always clear whose list is showing.
    function buildPairDetailsHtml(atlas, osm, options) {
        const details = [];
        if (!options.hideRoutesAndNotes && SharedUtils.hasCapability('routes')) {
            const routeOptions = { enableRouteLink: options.enableRouteLinks !== false };
            details.push({
                source: 'atlas',
                label: `${SharedUtils.escapeHtml(SharedUtils.routeSourceLabel())} routes`,
                html: PopupUtils.normalizeRoutes(atlas.routes_gtfs).length ? PopupUtils.formatAtlasRouteList(atlas.routes_gtfs, routeOptions) : null,
            });
            details.push({
                source: 'osm',
                label: 'OSM routes',
                html: PopupUtils.normalizeRoutes(osm.routes_osm).length ? PopupUtils.formatRouteList(osm.routes_osm, routeOptions) : null,
            });
        }
        const tags = options.hideRoutesAndNotes ? null : buildOsmTagsTable(osm.osm_tags);
        if (tags) details.push({ source: 'osm', label: `Tags (${tags.count})`, html: tags.html });
        if (details.length === 0) return '';

        const tabs = [];
        const panels = [];
        details.forEach(detail => {
            if (!detail.html) {
                tabs.push(`<button type="button" class="popup-details-tab" data-source="${detail.source}" disabled title="No route information available">${detail.label}</button>`);
                return;
            }
            const id = `popup-detail-${++detailPanelCount}`;
            tabs.push(`<button type="button" class="popup-details-tab" data-source="${detail.source}" aria-expanded="false" aria-controls="${id}" onclick="PopupRenderer.toggleMatchDetail(this)">${detail.label}</button>`);
            panels.push(`<div id="${id}" class="popup-details-panel" data-source="${detail.source}" role="region" aria-label="${detail.label}" hidden>${detail.html}</div>`);
        });
        return `<div class="popup-details"><div class="popup-details-tabs">${tabs.join('')}</div>${panels.join('')}</div>`;
    }

    // One pair compared field by field, at the width of a single card.
    function buildCompareViewHtml(pair, options, index) {
        const { atlas, osm } = pair;
        const cell = value => hasValue(value) ? value : '<span class="popup-compare-missing">–</span>';
        const fieldRows = buildCompareRows(atlas, osm, options).map(row => {
            const marker = row.differs ? ' class="is-different" title="ATLAS and OSM differ"' : '';
            return `<tr${marker}><th scope="row">${row.label}</th><td>${cell(row.atlas)}</td><td>${cell(row.osm)}</td></tr>`;
        }).join('');
        const pairRows = [
            ['Distance', formatDistanceMeters(pair.distance_m)],
            ['Match Type', hasValue(pair.match_type) ? buildMatchTypeHtml(pair.match_type) : null],
        ].filter(([, value]) => hasValue(value))
            .map(([label, value]) => `<tr class="popup-compare-pair"><th scope="row">${label}</th><td colspan="2">${value}</td></tr>`)
            .join('');
        const atlasLinks = compareLinksHtml('atlas', atlas, options);
        const osmLinks = compareLinksHtml('osm', osm, options);
        const linksRow = atlasLinks || osmLinks
            ? `<tr class="popup-compare-links"><td></td><td>${atlasLinks}</td><td>${osmLinks}</td></tr>`
            : '';

        return `
            <div class="popup-compare"${index > 0 ? ' hidden' : ''}>
                <table class="popup-table popup-compare-table">
                    <colgroup><col class="popup-compare-label"><col><col></colgroup>
                    <thead><tr><td></td><th scope="col" class="popup-compare-atlas">${compareSourceHeadHtml('atlas', atlas)}</th><th scope="col" class="popup-compare-osm">${compareSourceHeadHtml('osm', osm)}</th></tr></thead>
                    <tbody>${fieldRows}${pairRows}${linksRow}</tbody>
                </table>
                ${buildPairDetailsHtml(atlas, osm, options)}
            </div>`;
    }

    // Names a match by what tells it apart from the stop's other matches.
    function matchTabTitle(pair, counterpartType) {
        const data = pair[counterpartType];
        if (counterpartType === 'osm') return getOsmTypeDisplay(data, false) || `Node ${data.osm_node_id}`;
        if (hasValue(data.atlas_designation)) return `Platform ${data.atlas_designation}`;
        // Without a platform code, the SLOID's own part tells the stops apart.
        return String(data.sloid || '').replace(/^[a-z]{2}:\d+:sloid:/i, '') || 'Stop';
    }

    // With several matches, tabs choose the pair the table shows.
    function buildMatchPickerHtml(pairs, counterpartType) {
        const titles = pairs.map(pair => matchTabTitle(pair, counterpartType));
        const tabs = pairs.map((pair, index) => {
            const repeated = titles.filter(title => title === titles[index]).length > 1;
            const title = SharedUtils.escapeHtml(String(repeated ? `${titles[index]} ${index + 1}` : titles[index]));
            const distance = formatDistanceMeters(pair.distance_m);
            return `<button type="button" role="tab" class="popup-match-tab" data-index="${index}" aria-selected="${index === 0}" onclick="PopupRenderer.selectMatch(this)">
                    <span class="popup-match-tab-title">${title}</span>${distance ? `<span class="popup-match-tab-distance">${distance}</span>` : ''}
                </button>`;
        }).join('');
        return `<div class="popup-match-picker" role="tablist" aria-label="Matches" data-source="${counterpartType}">${tabs}</div>`;
    }

    function generateUnifiedBubbleHtml(stop, initialViewType, options = {}) {
        const pairs = buildMatchPairs(stop);
        if (pairs.length === 0) return '<!-- No matches to display -->';
        const counterpartType = pairs.length > 1 && pairs[0].atlas === pairs[1].atlas ? 'osm' : 'atlas';
        return buildMatchesBarHtml()
            + (pairs.length > 1 ? buildMatchPickerHtml(pairs, counterpartType) : '')
            + pairs.map((pair, index) => buildCompareViewHtml(pair, options, index)).join('');
    }

    function generatePopupHtml(stop, initialViewType, options = {}) {
        const initialContent = generateInitialBubbleHtml(stop, initialViewType, options);
        const unifiedContent = stopHasMatches(stop)
            ? generateUnifiedBubbleHtml(stop, initialViewType, options)
            : '';

        return wrapPopupViews(initialContent, unifiedContent, initialViewType, stop.id);
    }

    function toggleMatchesView(buttonElement, showUnified) {
        const container = buttonElement.closest('.popup-outer-wrapper');
        if (!container) return;

        const initialView = container.querySelector('.popup-initial-view');
        const unifiedView = container.querySelector('.popup-unified-view');
        if (initialView) initialView.style.display = showUnified ? 'none' : 'block';
        if (unifiedView) unifiedView.style.display = showUnified ? 'block' : 'none';
        container.setAttribute('data-view-mode', showUnified ? 'unified' : 'initial');

        refreshPopupLayout(container);
    }

    // Lay out in the same frame, so the popup never shows at an intermediate size.
    function refreshPopupLayout(element) {
        const popupElement = element.closest('.leaflet-popup');
        const popupInstance = popupElement && popupElement._leaflet_popup_instance;
        if (popupInstance && typeof popupInstance.refreshLayout === 'function') {
            popupInstance.refreshLayout();
        }
    }

    function selectMatch(tabElement) {
        const view = tabElement.closest('.popup-unified-view');
        if (!view) return;
        const selected = Number(tabElement.dataset.index);
        view.querySelectorAll('.popup-compare').forEach((page, index) => { page.hidden = index !== selected; });
        view.querySelectorAll('.popup-match-tab').forEach(tab => {
            tab.setAttribute('aria-selected', String(tab === tabElement));
        });
        refreshPopupLayout(view);
    }

    function toggleMatchDetail(tabElement) {
        const group = tabElement.closest('.popup-details');
        if (!group) return;
        const opening = tabElement.getAttribute('aria-expanded') !== 'true';
        group.querySelectorAll('.popup-details-tab[aria-controls]').forEach(tab => {
            const open = opening && tab === tabElement;
            tab.setAttribute('aria-expanded', String(open));
            const panel = group.querySelector(`#${tab.getAttribute('aria-controls')}`);
            if (panel) panel.hidden = !open;
        });
        refreshPopupLayout(group);
    }

    function showMatches(buttonElement) {
        toggleMatchesView(buttonElement, true);
    }

    function hideMatches(buttonElement) {
        toggleMatchesView(buttonElement, false);
    }

    PopupRenderer.renderBubble = renderBubble;
    PopupRenderer.generateSingleAtlasBubbleHtml = generateSingleAtlasBubbleHtml;
    PopupRenderer.generateSingleOsmBubbleHtml = generateSingleOsmBubbleHtml;
    PopupRenderer.generateInitialBubbleHtml = generateInitialBubbleHtml;
    PopupRenderer.generateUnifiedBubbleHtml = generateUnifiedBubbleHtml;
    PopupRenderer.generatePopupHtml = generatePopupHtml;
    PopupRenderer.generateGtfsStopIdSloidPopupHtml = generateGtfsStopIdSloidPopupHtml;
    PopupRenderer.showMatches = showMatches;
    PopupRenderer.hideMatches = hideMatches;
    PopupRenderer.selectMatch = selectMatch;
    PopupRenderer.toggleMatchDetail = toggleMatchDetail;
    PopupRenderer.parseOsmElementRef = parseOsmElementRef;
    global.PopupRenderer = PopupRenderer;
    global.MapComponents = global.MapComponents || {};
    global.MapComponents.PopupRenderer = PopupRenderer;
})(window);
