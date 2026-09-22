const path = require('path');
const loadBrowserScript = require('./load-browser-script');

describe('operator map filters', () => {
    let updateActiveFiltersFromControls;

    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/jquery-lite.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/utils.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/components/filter-chip-utils.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/pages/filters.js'));
        updateActiveFiltersFromControls = window.updateActiveFilters;
        const jquery = window.$;
        window.$ = Object.assign(function (selector) {
            if (selector === document) return { ready: jest.fn(), on: jest.fn() };
            return jquery(selector);
        }, jquery);
        window.L = { layerGroup: () => ({ clearLayers: jest.fn() }) };
        window.AppConstants = { MAP: {}, DATA_LOADING: {}, COLORS: {} };
        loadBrowserScript(path.join(__dirname, '../../static/js/pages/main.js'));
    });

    beforeEach(() => {
        document.body.innerHTML = '<div id="activeFilters"></div><input type="checkbox" id="filterMissingOsmOperatorWikidata">';
        activeFilters.atlasOperators = [];
        activeFilters.missingOsmOperatorWikidata = false;
        window.updateActiveFilters = updateActiveFiltersFromControls;
        window.loadDataForViewport = jest.fn();
        window.updateHeaderSummary = jest.fn();
        activeFilters.osmOperators = [];
        activeFilters.osmOperatorWikidata = [];
        window.osmOperatorDropdown = { setSelection: jest.fn() };
        window.osmOperatorWikidataDropdown = { setSelection: jest.fn() };
        history.replaceState({}, '', '/');
    });

    test('loads Wikidata deep links and sends the selected values with map requests', () => {
        history.replaceState({}, '', '/?osm_operator_wikidata=Q1,Q2&osm_operator_wikidata=Q1');
        window.restoreOperatorFiltersFromUrl();
        expect(activeFilters.osmOperatorWikidata).toEqual(['Q1', 'Q2']);
        expect(window.osmOperatorWikidataDropdown.setSelection).toHaveBeenCalledWith(['Q1', 'Q2']);
        expect(window.appendCurrentFilterParams({})).toEqual({ osm_operator_wikidata: 'Q1,Q2' });
        expect(getActiveFilterCount()).toBe(2);
        updateFiltersUI();
        expect(document.getElementById('activeFilters').textContent).toContain('OSM Operator Wikidata: Q1');
        window.removeSimpleArrayFilter('osmOperatorWikidata', 'Q1');
        expect(window.appendCurrentFilterParams({})).toEqual({ osm_operator_wikidata: 'Q2' });
        expect(window.osmOperatorWikidataDropdown.setSelection).toHaveBeenLastCalledWith(['Q2']);
    });

    test('clears Wikidata selections along with the other filters', () => {
        activeFilters.osmOperatorWikidata = ['Q1'];
        activeFilters.missingOsmOperatorWikidata = true;
        document.getElementById('filterMissingOsmOperatorWikidata').checked = true;
        window.updateActiveFilters = jest.fn();
        window.updateHeaderSummary = jest.fn();
        window.clearAllFilters();
        expect(activeFilters.osmOperatorWikidata).toEqual([]);
        expect(activeFilters.missingOsmOperatorWikidata).toBe(false);
        expect(document.getElementById('filterMissingOsmOperatorWikidata').checked).toBe(false);
        expect(window.osmOperatorWikidataDropdown.setSelection).toHaveBeenCalledWith([]);
        expect(window.appendCurrentFilterParams({})).toEqual({});
    });

    test('decodes OSM operator names from card links', () => {
        history.replaceState({}, '', '/?osm_operator=Example+%26+Co');
        window.restoreOperatorFiltersFromUrl();
        expect(activeFilters.osmOperators).toEqual(['Example & Co']);
        expect(window.appendCurrentFilterParams({})).toEqual({ osm_operator: 'Example & Co' });
    });

    test('restores the operator and missing-tag combination from the coverage link', () => {
        history.replaceState({}, '', '/?atlas_operator=EX&missing_osm_operator_wikidata=true');
        window.restoreOperatorFiltersFromUrl();
        expect(window.appendCurrentFilterParams({})).toEqual({
            atlas_operator: 'EX', missing_osm_operator_wikidata: 'true'
        });
        expect(getActiveFilterCount()).toBe(2);
        expect(document.getElementById('filterMissingOsmOperatorWikidata').checked).toBe(true);
        updateFiltersUI();
        expect(document.getElementById('activeFilters').textContent).toContain('No Wikidata tag');
        expect(document.querySelector('[data-target="#filterMissingOsmOperatorWikidata"]')).not.toBeNull();
    });

    test('toggling missing tags replaces specific Wikidata values and refreshes the map', () => {
        window.initFilterEventHandlers();
        activeFilters.osmOperatorWikidata = ['Q1'];
        window.$('#filterMissingOsmOperatorWikidata').prop('checked', true).trigger('change');
        expect(activeFilters.osmOperatorWikidata).toEqual([]);
        expect(window.osmOperatorWikidataDropdown.setSelection).toHaveBeenCalledWith([]);
        expect(window.appendCurrentFilterParams({})).toEqual({ missing_osm_operator_wikidata: 'true' });
        expect(window.loadDataForViewport).toHaveBeenCalled();
        window.$('#filterMissingOsmOperatorWikidata').prop('checked', false).trigger('change');
        expect(window.appendCurrentFilterParams({})).toEqual({});
    });

});
