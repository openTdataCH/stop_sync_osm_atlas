(function(global){
    'use strict';

    const PopupUtils = {};

    function normalizeRoutes(routes){
        if(!routes){ return []; }
        if(typeof routes === 'string'){
            try{ routes = JSON.parse(routes); }catch(e){ return []; }
        }
        if(Array.isArray(routes)){ return routes.filter(Boolean); }
        return [routes];
    }

    function groupRoutes(routes){
        const groups = {};
        routes.forEach(route => {
            if(!route) return;
            const routeId = route.route_id || 'unknown';
            const routeName = route.route_short_name || route.route_name || route.route_id || 'Unnamed Route';
            if(!groups[routeId]){
                groups[routeId] = { name: routeName, directions: [], routeId };
            }
            if(route.direction_id !== undefined && !groups[routeId].directions.includes(route.direction_id)){
                groups[routeId].directions.push(route.direction_id);
            }
        });
        return groups;
    }

    function formatRouteList(routes){
        routes = normalizeRoutes(routes);
        if(routes.length === 0){ return '<i>No route information available</i>'; }
        const routeGroups = groupRoutes(routes);
        const itemsHtml = Object.values(routeGroups).map(group => {
            const directions = group.directions.slice().sort();
            const directionsStr = directions.length > 0 ? `Dir:${directions.join(',')}` : '';
            const routeIdLink = group.routeId !== 'unknown'
                ? `(ID: <a href="#" onclick="filterByRoute('${group.routeId}', '${directions.join(',')}'); return false;">${group.routeId}</a>)`
                : '';
            return `<li>${group.name} ${routeIdLink} ${directionsStr}</li>`;
        }).join('');
        return `<ul class="route-list" style="margin-top: 5px; padding-left: 15px;">${itemsHtml}</ul>`;
    }

    function formatUnifiedRouteList(routes) {
        routes = normalizeRoutes(routes);
        if (routes.length === 0) { return '<i>No route information available</i>'; }
        const itemsHtml = routes.map(route => {
            if (!route) return '';
            const source = (route.source || '').toUpperCase();
            const displayName = route.route_name_short || route.route_name_long || route.line_name || route.route_id || 'Unnamed Route';
            const direction = route.direction_name || route.direction_uic || route.direction_id || '';
            const right = [route.route_id || '', route.line_name || ''].filter(Boolean).join(' / ');
            const sourceChip = source ? `<span class="chip">${source}</span>` : '';
            const dirStr = direction ? `<small>${direction}</small>` : '';
            return `<li>${sourceChip} ${displayName} ${dirStr} ${right ? `<small>(${right})</small>` : ''}</li>`;
        }).join('');
        return `<ul class="route-list" style="margin-top: 5px; padding-left: 15px;">${itemsHtml}</ul>`;
    }

    function categorizeRoutes(atlasRoutes, osmRoutes){
        const atlasArr = normalizeRoutes(atlasRoutes);
        const osmArr   = normalizeRoutes(osmRoutes);
        const matched = [];
        const atlasOnly = [...atlasArr];
        const osmOnly   = [...osmArr];
        atlasArr.forEach(atlasRoute => {
            if(!atlasRoute || !atlasRoute.route_id) return;
            const matchIdx = osmArr.findIndex(osmRoute => osmRoute && osmRoute.route_id === atlasRoute.route_id && osmRoute.direction_id === atlasRoute.direction_id);
            if(matchIdx !== -1){
                const osmRoute = osmArr[matchIdx];
                matched.push({
                    route_id: atlasRoute.route_id,
                    direction_id: atlasRoute.direction_id,
                    route_short_name: atlasRoute.route_short_name || osmRoute.route_name,
                    route_long_name: atlasRoute.route_long_name,
                    route_name: osmRoute.route_name
                });
                const atlasIdx = atlasOnly.findIndex(r => r && r.route_id === atlasRoute.route_id && r.direction_id === atlasRoute.direction_id);
                if(atlasIdx !== -1) atlasOnly.splice(atlasIdx, 1);
                const osmIdx = osmOnly.findIndex(r => r && r.route_id === osmRoute.route_id && r.direction_id === osmRoute.direction_id);
                if(osmIdx !== -1) osmOnly.splice(osmIdx, 1);
            }
        });
        return { matchedRoutes: matched, atlasOnlyRoutes: atlasOnly, osmOnlyRoutes: osmOnly };
    }

    function createCollapsible(title, content, isExpanded = false) {
        if (content === "<i>No route information available</i>") {
            return content + "<br>";
        }
        const id = 'collapse-' + Math.random().toString(36).substring(2, 9);
        return `
            <div class="collapsible">
                <button type="button" class="btn btn-sm btn-outline-secondary" 
                        onclick="PopupUtils.toggleCollapsible('${id}')">
                    ${title} <span id="${id}-arrow">${isExpanded ? '▲' : '▼'}</span>
                </button>
                <div id="${id}" class="collapsible-content" 
                    style="display: ${isExpanded ? 'block' : 'none'}; 
                          margin-top: 5px; 
                          border-left: 3px solid #ccc; 
                          padding-left: 8px;
                          max-height: 150px;
                          overflow-y: auto;
                          scrollbar-width: thin;
                          scrollbar-color: #6c757d #e9ecef;">
                    ${content}
                </div>
            </div>
        `;
    }

    function toggleCollapsible(id) {
        const element = document.getElementById(id);
        const arrow = document.getElementById(id + '-arrow');
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

    function createFilterLink(value, type, displayText){
        if(!value) return 'N/A';
        const text = displayText || value;
        return `<a href="#" onclick="addCustomFilter('${value}', '${type}'); return false;">${text}</a>`;
    }

    PopupUtils.normalizeRoutes = normalizeRoutes;
    PopupUtils.groupRoutes     = groupRoutes;
    PopupUtils.formatRouteList = formatRouteList;
    PopupUtils.formatUnifiedRouteList = formatUnifiedRouteList;
    PopupUtils.categorizeRoutes= categorizeRoutes;
    PopupUtils.createFilterLink= createFilterLink;
    PopupUtils.createCollapsible = createCollapsible;
    PopupUtils.toggleCollapsible = toggleCollapsible;
    PopupUtils.formatRoutesDisplay = formatRoutesDisplay;
    global.PopupUtils = PopupUtils;

})(window);


