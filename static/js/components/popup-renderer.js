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

    function buildPopupToggleButtonHtml(showUnified) {
        const handlerName = showUnified ? 'showMatches' : 'hideMatches';
        const label = showUnified ? 'See Matches' : 'Close Matches';
        return `<button class="btn btn-sm popup-action-btn" onclick="PopupRenderer.${handlerName}(this)">${label}</button>`;
    }

    function buildActionOnlyFooterHtml(actionButtonHtml) {
        if (!actionButtonHtml) {
            return '';
        }

        return `<div class="bubble-footer"><div class="bubble-btn-row">${actionButtonHtml}</div></div>`;
    }

    function buildDetailListHtml(items, formatter, emptyMessage = 'None') {
        if (!Array.isArray(items) || items.length === 0) {
            return `<p class="popup-empty-state">${emptyMessage}</p>`;
        }

        return `<ul class="popup-detail-list">${items.map(item => `<li>${formatter(item)}</li>`).join('')}</ul>`;
    }

    function buildDetailSectionHtml(title, contentHtml) {
        return `<section class="popup-detail-section"><h6>${title}</h6>${contentHtml}</section>`;
    }

    function formatPopupMono(value) {
        return `<span class="popup-mono">${value || 'N/A'}</span>`;
    }

    function formatDetailDistanceMeters(distanceM) {
        return formatDistanceMeters(distanceM) || 'N/A';
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

    function renderBubbleCard(options) {
        const {
            type,
            unmatched = false,
            headerHtml,
            rows = [],
            sectionsHtml = '',
            footerHtml = '',
            osmEditorUrl = null,
        } = options;

        const bubbleClass = getBubbleClass(type);
        const unmatchedClass = unmatched ? ' unmatched' : '';
        const osmEditorLinkHtml = type === 'osm' && osmEditorUrl
            ? `<div class="osm-editor-link-container mt-2"><a href="${osmEditorUrl}" class="osm-editor-link" target="_blank" rel="noopener noreferrer"><i class="fas fa-external-link-alt"></i> Edit in OSM iD Editor</a></div>`
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

    function buildGtfsBubbleHeader(unmatched) {
        return `<h5>${unmatched ? 'Unmatched ' : ''}GTFS Stop</h5>`;
    }

    function buildRoutesFooterHtml(data, type, unmatched, hideRoutesAndNotes, actionButtonHtml, options = {}) {
        if (hideRoutesAndNotes) {
            return actionButtonHtml ? `<div class="bubble-footer"><div class="bubble-btn-row">${actionButtonHtml}</div></div>` : '';
        }

        const routes = type === 'atlas' ? data.routes_atlas : data.routes_osm;
        const formattedRoutes = type === 'atlas'
            ? PopupUtils.formatAtlasRouteList(routes, { enableRouteLink: !(options.enableRouteLinks === false) })
            : PopupUtils.formatRouteList(routes, { enableRouteLink: !(options.enableRouteLinks === false) });
        const collapsible = PopupUtils.createCollapsible('Routes', formattedRoutes, COLLAPSIBLE_DEFAULT_EXPANDED);
        const buttons = `${collapsible.buttonHtml || ''}${actionButtonHtml || ''}`;

        if (!buttons && !collapsible.panelHtml) return '';

        return `
            <div class="bubble-footer">
                ${buttons ? `<div class="bubble-btn-row">${buttons}</div>` : ''}
                ${collapsible.panelHtml || ''}
            </div>`;
    }

    function buildAtlasRows(data, unmatched, options = {}) {
        const rows = [];
        const mismatchText = data.isOperatorMismatch && !unmatched
            ? ' <span class="operator-mismatch">(!Operator Mismatch!)</span>'
            : '';

        rows.push(['Sloid', unmatched ? (data.sloid || 'N/A') : buildFilterText(data.sloid, 'atlas', options)]);
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

        if (unmatched) {
            if (hasValue(data.uic_ref)) rows.push(['UIC Ref', buildFilterText(data.uic_ref, 'station', options)]);
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

        if (!options.hideMatchMetadata) {
            const distance = formatDistanceMeters(data.distance_m);
            if (distance) rows.push(['Distance', distance]);
            rows.push(['Match Type', buildMatchTypeHtml(data.match_type)]);
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
        const footerHtml = buildRoutesFooterHtml(data, type, unmatched, hideRoutesAndNotes, actionButtonHtml, opts);

        return renderBubbleCard({
            type,
            unmatched,
            headerHtml: bubbleHeader,
            rows,
            footerHtml,
            osmEditorUrl: type === 'osm' ? buildOsmEditorUrl(data.osm_node_id) : null,
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
        return `
            <div class="matches-container">${cardsHtml}</div>
            <div class="popup-actions mt-2">${buildPopupToggleButtonHtml(false)}</div>`;
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
            ? buildPopupToggleButtonHtml(true)
            : '';

        return renderBubbleCard({
            type: 'atlas',
            unmatched,
            headerHtml: buildBubbleHeader(data, 'atlas', unmatched),
            rows: buildAtlasReferenceRows(data, unmatched, options),
            footerHtml: buildActionOnlyFooterHtml(actionButtonHtml),
        });
    }

    function renderAtlasReferenceMatchBubbleHtml(data, options = {}) {
        return renderBubbleCard({
            type: 'atlas',
            unmatched: false,
            headerHtml: buildBubbleHeader(data, 'atlas', false),
            rows: buildAtlasReferenceMatchRows(data, options),
        });
    }

    function renderGtfsReferenceSummaryBubbleHtml(data, options = {}) {
        const unmatched = Number(data.matched_sloid_count || 0) === 0;
        const actionButtonHtml = !options.suppressMatchToggle && gtfsReferenceHasMatches(data)
            ? buildPopupToggleButtonHtml(true)
            : '';

        return renderBubbleCard({
            type: 'gtfs',
            unmatched,
            headerHtml: buildGtfsBubbleHeader(unmatched),
            rows: buildGtfsReferenceRows(data),
            footerHtml: buildActionOnlyFooterHtml(actionButtonHtml),
        });
    }

    function renderGtfsReferenceMatchBubbleHtml(data) {
        return renderBubbleCard({
            type: 'gtfs',
            unmatched: false,
            headerHtml: buildGtfsBubbleHeader(false),
            rows: buildGtfsReferenceMatchRows(data),
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
            }, { suppressMatchToggle: true })),
            ...(Array.isArray(data.matched_sloids) ? data.matched_sloids.map(function (item) {
                return wrapPopupMatchCard(renderAtlasReferenceMatchBubbleHtml(item, options));
            }) : [])
        ].join('');

        return buildUnifiedPopupViewHtml(cardsHtml);
    }

    function buildAtlasReferenceUnifiedBubbleHtml(data) {
        if (!atlasReferenceHasMatches(data)) {
            return '';
        }

        const cardsHtml = [
            wrapPopupMatchCard(renderAtlasReferenceSummaryBubbleHtml({
                ...data,
                matched_gtfs_count: data.matched_gtfs_count,
                same_uic_gtfs_count: data.same_uic_gtfs_count,
            }, { suppressMatchToggle: true })),
            ...(Array.isArray(data.matched_gtfs) ? data.matched_gtfs.map(function (item) {
                return wrapPopupMatchCard(renderGtfsReferenceMatchBubbleHtml(item));
            }) : [])
        ].join('');

        return buildUnifiedPopupViewHtml(cardsHtml);
    }

    function generateAtlasReferenceBubbleHtml(data, options = {}) {
        const content = renderAtlasReferenceSummaryBubbleHtml(data, options);
        const unifiedContent = buildAtlasReferenceUnifiedBubbleHtml(data);

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
        const isUnmatched = stop.stop_type === 'atlas_unmatched' || stop.stop_type === 'osm_unmatched';
        const actionButtonHtml = stopHasMatches(stop)
            ? buildPopupToggleButtonHtml(true)
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

        return `
            <div class="matches-container">${cardsHtml}</div>
            <div class="popup-actions mt-2">${buildPopupToggleButtonHtml(false)}</div>`;
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
    global.PopupRenderer = PopupRenderer;
})(window);


