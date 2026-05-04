(function (global) {
    'use strict';

    const PopupUtils = {};

    function hasGlobalFunction(name) {
        return typeof global[name] === 'function';
    }

    function escapeInlineJsString(value) {
        return String(value)
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'");
    }

    function normalizeRoutes(routes) {
        if (!routes) { return []; }
        if (typeof routes === 'string') {
            try { routes = JSON.parse(routes); } catch (e) { return []; }
        }
        if (Array.isArray(routes)) { return routes.filter(Boolean); }
        return [routes];
    }

    function groupRoutes(routes) {
        const groups = {};
        routes.forEach(route => {
            if (!route) return;
            const internalRouteId = route.internal_route_id || route.route_id || null;
            const displayRouteId = route.display_route_id || route.route_id || null;
            const routeId = displayRouteId || internalRouteId || 'unknown';
            const routeName = route.route_short_name || route.route_name || displayRouteId || 'Unnamed Route';
            if (!groups[routeId]) {
                groups[routeId] = { name: routeName, directions: [], routeId, internalRouteId, displayRouteId };
            }
            if (route.direction_id !== undefined && !groups[routeId].directions.includes(route.direction_id)) {
                groups[routeId].directions.push(route.direction_id);
            }
        });
        return groups;
    }

    function formatRouteList(routes, options = {}) {
        routes = normalizeRoutes(routes);
        if (routes.length === 0) { return '<i>No route information available</i>'; }
        const routeGroups = groupRoutes(routes);
        const itemsHtml = Object.values(routeGroups).map(group => {
            const directions = group.directions.slice().sort();
            const directionsStr = directions.length > 0 ? `Dir: ${directions.join(',')}` : '';
            const filterRouteId = group.internalRouteId || group.routeId;
            const safeRouteId = escapeInlineJsString(filterRouteId);
            const safeDirections = escapeInlineJsString(directions.join(','));
            const routeIdText = group.displayRouteId || group.routeId;
            const routeIdLink = filterRouteId && routeIdText !== 'unknown' && options.enableRouteLink !== false && hasGlobalFunction('filterByRoute')
                ? `<a href="#" onclick="filterByRoute('${safeRouteId}', '${safeDirections}'); return false;">${routeIdText}</a>`
                : routeIdText;

            const hasDistinctName = Boolean(group.name) && group.name !== routeIdText;
            const primaryText = hasDistinctName ? group.name : routeIdLink;
            const idSuffix = (routeIdText !== 'unknown' && hasDistinctName)
                ? `(ID: ${routeIdLink})`
                : '';

            return `<li>${primaryText} ${idSuffix} ${directionsStr}</li>`;
        }).join('');
        return `<ul class="route-list" style="margin-top: 5px; padding-left: 15px;">${itemsHtml}</ul>`;
    }

    function formatAtlasRouteList(routes, options = {}) {
        routes = normalizeRoutes(routes);
        if (routes.length === 0) { return '<i>No route information available</i>'; }

        const normalized = routes
            .filter(Boolean)
            .map(route => ({
                route_id: route.route_id,
                route_name: route.route_name_short || route.route_name_long || route.route_id || 'Unnamed Route',
                direction_id: route.direction_id,
            }));

        return formatRouteList(normalized, options);
    }

    function categorizeRoutes(atlasRoutes, osmRoutes) {
        const atlasArr = normalizeRoutes(atlasRoutes);
        const osmArr = normalizeRoutes(osmRoutes);
        const matched = [];
        const atlasOnly = [...atlasArr];
        const osmOnly = [...osmArr];
        atlasArr.forEach(atlasRoute => {
            if (!atlasRoute || !atlasRoute.route_id) return;
            const matchIdx = osmArr.findIndex(osmRoute => osmRoute && osmRoute.route_id === atlasRoute.route_id && osmRoute.direction_id === atlasRoute.direction_id);
            if (matchIdx !== -1) {
                const osmRoute = osmArr[matchIdx];
                matched.push({
                    route_id: atlasRoute.route_id,
                    direction_id: atlasRoute.direction_id,
                    route_short_name: atlasRoute.route_short_name || osmRoute.route_name,
                    route_long_name: atlasRoute.route_long_name,
                    route_name: osmRoute.route_name
                });
                const atlasIdx = atlasOnly.findIndex(r => r && r.route_id === atlasRoute.route_id && r.direction_id === atlasRoute.direction_id);
                if (atlasIdx !== -1) atlasOnly.splice(atlasIdx, 1);
                const osmIdx = osmOnly.findIndex(r => r && r.route_id === osmRoute.route_id && r.direction_id === osmRoute.direction_id);
                if (osmIdx !== -1) osmOnly.splice(osmIdx, 1);
            }
        });
        return { matchedRoutes: matched, atlasOnlyRoutes: atlasOnly, osmOnlyRoutes: osmOnly };
    }

    function createCollapsible(title, content, isExpanded = false) {
        if (content === "<i>No route information available</i>") {
            return { buttonHtml: '', panelHtml: content + "<br>" };
        }
        const id = 'collapse-' + Math.random().toString(36).substring(2, 9);
        const buttonHtml = `<button type="button" class="btn btn-sm popup-action-btn popup-routes-btn"
                    onclick="PopupUtils.toggleCollapsible('${id}')">
                <span class="btn-collapsible-title">${title}</span>
                <span id="${id}-arrow" class="btn-collapsible-arrow">${isExpanded ? '▲' : '▼'}</span>
            </button>`;
        const panelHtml = `<div id="${id}" class="collapsible-content shadow-inner"
                    style="display: ${isExpanded ? 'block' : 'none'};">
                ${content}
            </div>`;
        return { buttonHtml, panelHtml };
    }

    function toggleCollapsible(id) {
        const element = document.getElementById(id);
        const arrow = document.getElementById(id + '-arrow');
        if (!element || !arrow) return;
        if (element.style.display === 'none') {
            element.style.display = 'block';
            arrow.textContent = '▲';
        } else {
            element.style.display = 'none';
            arrow.textContent = '▼';
        }
    }

    function formatRoutesDisplay(atlasRoutes, osmRoutes, isOsmNode = false) {
        const { matchedRoutes = [], atlasOnlyRoutes = [], osmOnlyRoutes = [] } = categorizeRoutes(atlasRoutes, osmRoutes);
        if (matchedRoutes.length === 0 && atlasOnlyRoutes.length === 0 && osmOnlyRoutes.length === 0) {
            return '<i>No route information available</i>';
        }
        let html = '';
        function addSection(title, routesArr) {
            if (routesArr.length > 0) { html += `<div><strong>${title}:</strong>${formatRouteList(routesArr)}</div>`; }
        }
        if (isOsmNode) {
            addSection('Matched Routes', matchedRoutes);
            addSection('OSM-only Routes', osmOnlyRoutes);
        } else {
            addSection('Matched Routes', matchedRoutes);
            addSection('ATLAS-only Routes', atlasOnlyRoutes);
            addSection('OSM-only Routes', osmOnlyRoutes);
        }
        return html || '<i>No route information available</i>';
    }

    function createFilterLink(value, type, displayText, options = {}) {
        if (!value) return 'N/A';
        const text = displayText || value;
        if (options.enableFilterLink === false || !hasGlobalFunction('addCustomFilter')) {
            return text;
        }
        const safeValue = escapeInlineJsString(value);
        const safeType = escapeInlineJsString(type);
        return `<a href="#" onclick="addCustomFilter('${safeValue}', '${safeType}'); return false;">${text}</a>`;
    }

    PopupUtils.normalizeRoutes = normalizeRoutes;
    PopupUtils.groupRoutes = groupRoutes;
    PopupUtils.formatRouteList = formatRouteList;
    PopupUtils.formatAtlasRouteList = formatAtlasRouteList;
    PopupUtils.categorizeRoutes = categorizeRoutes;
    PopupUtils.createFilterLink = createFilterLink;
    PopupUtils.createCollapsible = createCollapsible;
    PopupUtils.toggleCollapsible = toggleCollapsible;
    PopupUtils.formatRoutesDisplay = formatRoutesDisplay;
    global.PopupUtils = PopupUtils;

})(window);


