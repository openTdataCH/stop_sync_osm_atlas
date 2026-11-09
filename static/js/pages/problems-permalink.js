// problems-permalink.js - Shareable URLs for the Problem Identification Page
//
// The query string holds the filters and the stop of the entry on screen:
//   ?problem_type=distance,unmatched&priority=1&atlas_operator=SBB
//    &bbox=<west,south,east,north>&sloid=<sloid>&osm=node|way/<id>
// A matched pair is named by both identifiers, an unmatched stop by its own,
// a duplicate group by one member. See documentation/2.9 Permalinks.md.

window.ProblemsPermalink = (function () {
    'use strict';

    const FILTER_KEYS = ['problem_type', 'priority', 'atlas_operator', 'bbox'];
    const STOP_KEYS = ['sloid', 'osm'];
    const ALL_KEYS = FILTER_KEYS.concat(STOP_KEYS);
    const PRIORITIES = ['1', '2', '3'];

    function csvValues(params, key) {
        const values = [];
        params.getAll(key).forEach(raw => {
            String(raw || '').split(',').forEach(value => {
                value = value.trim();
                if (value && !values.includes(value)) values.push(value);
            });
        });
        return values;
    }

    function osmPath(osmNodeId) {
        const ref = osmNodeId ? PopupRenderer.parseOsmElementRef(osmNodeId) : null;
        return ref && /^\d+$/.test(ref.id) ? ref.type + '/' + ref.id : null;
    }

    // Filters and focus stop from a query string. Unknown filter values are
    // dropped; the focus uses the stored identifiers ("way_<id>" for ways).
    function parse(search) {
        const params = new URLSearchParams(search);
        let problemTypes = csvValues(params, 'problem_type')
            .filter(type => ProblemsData.ALL_PROBLEM_TYPES.includes(type));
        if (problemTypes.length === ProblemsData.ALL_PROBLEM_TYPES.length) problemTypes = [];
        problemTypes = ProblemsData.ALL_PROBLEM_TYPES.filter(type => problemTypes.includes(type));

        const sloid = (params.get('sloid') || '').trim();
        const osm = /^(node|way)\/(\d+)$/.exec((params.get('osm') || '').trim());
        const focus = sloid || osm ? {
            sloid: sloid || null,
            osm_node_id: osm ? (osm[1] === 'way' ? 'way_' + osm[2] : osm[2]) : null
        } : null;
        const hasStopParam = params.has('sloid') || params.has('osm');

        return {
            problemTypes: problemTypes,
            priorities: PRIORITIES.filter(priority => csvValues(params, 'priority').includes(priority)),
            atlasOperators: csvValues(params, 'atlas_operator'),
            area: ProblemsArea.parseArea(params.get('bbox')),
            focus: focus,
            invalidStop: hasStopParam && !focus
        };
    }

    // The stop that names an entry (an array of problems at one place).
    function entryStopParams(entry) {
        const first = entry && entry[0];
        if (!first) return {};
        if (Array.isArray(first.members) && first.members.length) {
            // Duplicate groups: the representative SLOID of an ATLAS group, the
            // first node of an OSM group.
            if (first.group_type === 'atlas') return { sloid: first.sloid || first.members[0].sloid };
            return { osm: osmPath(first.members[0].osm_node_id) };
        }
        return { sloid: first.sloid || null, osm: osmPath(first.osm_node_id) };
    }

    function rowsOf(problem) {
        return Array.isArray(problem.members) && problem.members.length ? problem.members : [problem];
    }

    function entryMatchesFocus(entry, focus) {
        return (entry || []).some(problem => rowsOf(problem).some(row =>
            (!focus.sloid || row.sloid === focus.sloid) &&
            (!focus.osm_node_id || String(row.osm_node_id) === focus.osm_node_id)
        ));
    }

    function currentQuery() {
        const params = {
            problem_type: (ProblemsState.getSelectedProblemTypes() || []).join(','),
            priority: (ProblemsState.getSelectedPriorities() || []).join(','),
            atlas_operator: (ProblemsState.getSelectedAtlasOperators() || []).join(','),
            bbox: ProblemsArea.formatArea(ProblemsState.getArea())
        };
        return Permalinks.encodeParams(Object.assign(params, entryStopParams(ProblemsState.getCurrentEntryProblems())));
    }

    function currentSearch() {
        return Permalinks.buildSearch(window.location.search, ALL_KEYS, currentQuery());
    }

    // Writes the current filters and entry; called whenever either changes.
    function sync() {
        Permalinks.replaceUrl({ search: currentSearch() });
    }

    function copyCurrentLink(button) {
        return Permalinks.copyLink(button, Permalinks.pageUrl(currentSearch(), ''));
    }

    return {
        ALL_KEYS,
        parse,
        entryStopParams,
        entryMatchesFocus,
        sync,
        copyCurrentLink
    };
})();
