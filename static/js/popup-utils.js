(function(global){
    'use strict';

    const PopupUtils = {};

    /* ------------------------------------------------------------------
     *  Generic helpers
     * ------------------------------------------------------------------ */
    /**
     * Normalise a routes payload so that downstream helpers always deal
     * with an array of plain objects. Accepts:
     *   • undefined/null  -> returns []
     *   • JSON string     -> parsed to object/array or [] if invalid
     *   • single object   -> wrapped in an array
     *   • array           -> shallow-cloned & falsy items removed
     */
    function normalizeRoutes(routes){
        if(!routes){ return []; }

        // Parse JSON if a string is supplied (defensive – backend sometimes
        // serialises arrays as strings)
        if(typeof routes === 'string'){
            try{
                routes = JSON.parse(routes);
            }catch(e){
                console.warn('PopupUtils.normalizeRoutes – JSON parse failed', e);
                return [];
            }
        }

        if(Array.isArray(routes)){
            return routes.filter(Boolean);
        }

        // Fallback: wrap a single object
        return [routes];
    }

    /* ------------------------------------------------------------------
     *  Route helpers
     * ------------------------------------------------------------------ */
    /**
     * Group an array of route objects by route_id and collect all distinct
     * direction_id values.
     *
     * @param {Array<Object>} routes – normalised array from `normalizeRoutes`.
     * @returns {Object} e.g. { "A": { name:"SBB", directions:[0,1], routeId:"A" } }
     */
    function groupRoutes(routes){
        const groups = {};
        routes.forEach(route => {
            if(!route) return;
            const routeId = route.route_id || 'unknown';
            const routeName = route.route_short_name || route.route_name || route.route_id || 'Unnamed Route';

            if(!groups[routeId]){
                groups[routeId] = {
                    name: routeName,
                    directions: [],
                    routeId
                };
            }
            if(route.direction_id !== undefined && !groups[routeId].directions.includes(route.direction_id)){
                groups[routeId].directions.push(route.direction_id);
            }
        });
        return groups;
    }

    /**
     * Convert a route list (array or JSON string) into a ready-to-inject HTML
     * unordered list. Falls back to the standard 'No route information' message.
     */
    function formatRouteList(routes){
        routes = normalizeRoutes(routes);
        if(routes.length === 0){
            return '<i>No route information available</i>';
        }

        const routeGroups = groupRoutes(routes);
        const itemsHtml = Object.values(routeGroups).map(group => {
            const directions = group.directions.slice().sort();
            const directionsStr = directions.length > 0 ? `Dir:${directions.join(',')}` : '';

            // Keep current behaviour (inline click) for backwards-compat, will
            // be replaced by delegated events in a later refactor phase.
            const routeIdLink = group.routeId !== 'unknown'
                ? `(ID: <a href="#" onclick="filterByRoute('${group.routeId}', '${directions.join(',')}'); return false;">${group.routeId}</a>)`
                : '';

            return `<li>${group.name} ${routeIdLink} ${directionsStr}</li>`;
        }).join('');

        return `<ul class="route-list" style="margin-top: 5px; padding-left: 15px;">${itemsHtml}</ul>`;
    }

    /**
     * Convert an HRDF route list into a ready-to-inject HTML unordered list.
     */
    function formatHrdfRouteList(routes) {
        routes = normalizeRoutes(routes);
        if (routes.length === 0) {
            return '<i>No HRDF route information available</i>';
        }

        const itemsHtml = routes.map(route => {
            if (!route || !route.line_name) return '';

            const lineName = route.line_name;
            const directionName = route.direction_name || route.direction_uic || 'N/A';
            const filterLink = `<a href="#" onclick="filterByHrdfRoute('${lineName}'); return false;">${lineName}</a>`;
            
            return `<li>Line: ${filterLink} <br> <small>Direction: ${directionName}</small></li>`;
        }).join('');

        return `<ul class="route-list" style="margin-top: 5px; padding-left: 15px;">${itemsHtml}</ul>`;
    }

    /**
     * Categorise two arrays of routes into matched / atlas-only / osm-only.
     * Returns an object with those three arrays for easier consumption in
     * higher-level renderers.
     */
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

                // Remove from only-lists
                const atlasIdx = atlasOnly.findIndex(r => r && r.route_id === atlasRoute.route_id && r.direction_id === atlasRoute.direction_id);
                if(atlasIdx !== -1) atlasOnly.splice(atlasIdx, 1);
                const osmIdx = osmOnly.findIndex(r => r && r.route_id === osmRoute.route_id && r.direction_id === osmRoute.direction_id);
                if(osmIdx !== -1) osmOnly.splice(osmIdx, 1);
            }
        });
        return { matchedRoutes: matched, atlasOnlyRoutes: atlasOnly, osmOnlyRoutes: osmOnly };
    }

    /* ------------------------------------------------------------------
     *  Collapsible UI helpers
     * ------------------------------------------------------------------ */
    
    // Function to create a collapsible section
    function createCollapsible(title, content, isExpanded = false) {
        // If content is simply the "No route information available" message, return it directly with a line break
        if (content === "<i>No route information available</i>") {
            return content + "<br>";
        }
        
        const id = 'collapse-' + Math.random().toString(36).substring(2, 9); // Generate random ID
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

    // Helper function to toggle collapsible sections
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

    /* ------------------------------------------------------------------
     *  Route display helpers
     * ------------------------------------------------------------------ */
    
    // Function to format routes with matched vs. unmatched categorization
    function formatRoutesDisplay(atlasRoutes, osmRoutes, isOsmNode = false) {
        const {
            matchedRoutes = [],
            atlasOnlyRoutes = [],
            osmOnlyRoutes = []
        } = categorizeRoutes(atlasRoutes, osmRoutes);

        // Early exit if nothing to show
        if (matchedRoutes.length === 0 && atlasOnlyRoutes.length === 0 && osmOnlyRoutes.length === 0) {
            return '<i>No route information available</i>';
        }

        let html = '';

        // Section builders (helper internal)
        function addSection(title, routesArr) {
            if (routesArr.length > 0) {
                html += `<div><strong>${title}:</strong>${formatRouteList(routesArr)}</div>`;
            }
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

    /* ------------------------------------------------------------------
     *  Misc helpers
     * ------------------------------------------------------------------ */
    function createFilterLink(value, type, displayText){
        if(!value) return 'N/A';
        const text = displayText || value;
        // Inline onclick kept for backwards-compat; will be removed in later phase.
        return `<a href="#" onclick="addCustomFilter('${value}', '${type}'); return false;">${text}</a>`;
    }

    // expose
    PopupUtils.normalizeRoutes = normalizeRoutes;
    PopupUtils.groupRoutes     = groupRoutes;
    PopupUtils.formatRouteList = formatRouteList;
    PopupUtils.formatHrdfRouteList = formatHrdfRouteList;
    PopupUtils.categorizeRoutes= categorizeRoutes;
    PopupUtils.createFilterLink= createFilterLink;
    PopupUtils.createCollapsible = createCollapsible;
    PopupUtils.toggleCollapsible = toggleCollapsible;
    PopupUtils.formatRoutesDisplay = formatRoutesDisplay;

    global.PopupUtils = PopupUtils;

})(window); 