const path = require('path');
const loadBrowserScript = require('./load-browser-script');

const CONTROLS = `
  <div id="activeFilters"></div>
  <input type="checkbox" id="masterMatchedCheckbox">
  <input type="checkbox" class="filter-match-method" id="filterIdentifier" value="identifier">
  <input type="checkbox" class="filter-match-method" id="filterReference" value="reference">
  <input type="checkbox" id="masterUnmatchedAtlasCheckbox">
  <input type="checkbox" class="filter-unmatched-method" id="filterNoNearbyOSM" value="no_nearby_counterpart">
  <input type="checkbox" class="filter-unmatched-method" id="filterOSMNearby" value="osm_within_50m">
  <input type="checkbox" id="masterUnmatchedOsmCheckbox">
  <input type="checkbox" id="masterDisusedOsmCheckbox">
  <input type="checkbox" class="filter-transport-type" id="filterPlatform" value="platform">
  <input type="checkbox" class="filter-transport-type" id="filterTramStop" value="tram_stop">
  <input type="checkbox" class="filter-osm-entity-type" id="filterOsmWay" value="way">
  <input type="checkbox" id="filterOsmGroup">
  <input type="checkbox" class="filter-osm-group-type" id="filterOsmTwoSided" value="ptv2_two_sided_stop">
  <input type="checkbox" id="filterDuplicatesOnly">
  <input type="checkbox" id="filterMissingOsmOperatorWikidata">
  <input type="number" id="topDistance" value="10"><button id="toggleTopNBtn"></button>
  <div id="topNDistancesContainer"></div><div id="topNDistancesMessage"></div>
  <input type="checkbox" id="masterProblemsCheckbox"><label for="masterProblemsCheckbox">All problems</label>
  <input type="checkbox" class="filter-problem-type" id="problemType-distance" value="distance"><label for="problemType-distance">Distance</label>
  <input type="checkbox" class="filter-problem-type" id="problemType-unmatched" value="unmatched"><label for="problemType-unmatched">Unmatched</label>
  <input type="checkbox" class="filter-problem-priority" id="problemPriority-1" value="1"><label for="problemPriority-1">P1</label>
  <input type="checkbox" class="filter-problem-priority" id="problemPriority-2" value="2"><label for="problemPriority-2">P2</label>`;

describe('map filter links', () => {
    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/components/filter-chip-utils.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/pages/filters.js'));
    });

    beforeEach(() => {
        document.body.innerHTML = CONTROLS;
        window.setupMasterCheckbox('#masterMatchedCheckbox', '.filter-match-method');
        window.setupMasterCheckbox('#masterUnmatchedAtlasCheckbox', '.filter-unmatched-method');
        window.setupMasterCheckbox('#filterOsmGroup', '.filter-osm-group-type');
        window.setupMasterCheckbox('#masterProblemsCheckbox', '.filter-problem-type');
        Object.assign(activeFilters, {
            station: [], stationTypes: [], routeDirections: [], routeVariants: [],
            atlasOperators: [], osmOperators: [], osmOperatorWikidata: [], topN: null
        });
        window.loadDataForViewport = jest.fn();
        window.loadTopNMatches = jest.fn();
        window.topNLayer = { clearLayers: jest.fn() };
        window.invalidateViewportCache = jest.fn();
        global.fetch = jest.fn(() => Promise.resolve({ ok: false }));
        history.replaceState({}, '', '/');
    });

    afterEach(() => {
        delete global.fetch;
    });

    test('search filters are written as link text and read back', () => {
        const cases = [
            ['station', '8503000', '', 'uic:8503000'],
            ['atlas', 'ch:1:sloid:3000:501:33', '', 'source:ch:1:sloid:3000:501:33'],
            ['osm', '123', '', 'node/123'],
            ['osm', 'way_45', '', 'way/45'],
            ['route', '91-10-A-j26-1', '0', 'route:91-10-A-j26-1 dir:0'],
            ['route', 'city:A', '', 'route:city:A']
        ];
        cases.forEach(([kind, value, direction, text]) => {
            expect(window.searchFilterText(kind, value, direction)).toBe(text);
            expect(window.parseSearchFilterText(text)).toEqual(kind === 'route' ? { kind, value, direction } : { kind, value });
        });
        expect(window.parseSearchFilterText('bogus:1')).toBeNull();
        expect(window.parseSearchFilterText('route:a b')).toBeNull();
    });

    test('a link restores the controls and search filters it names, and writes back the same link', () => {
        const query = 'stop_filter=osm_unmatched,osm_disused&match_method=reference,no_nearby_counterpart'
            + '&transport_types=platform&osm_entity_types=way&osm_group_types=all&show_duplicates_only=true'
            + '&top_n=15&search=uic:8503000&search=way/45&search=route:91-10-A-j26-1+dir:0';
        restoreFiltersFromUrl('?' + query);
        updateActiveFilters();

        expect(['filterReference', 'filterNoNearbyOSM', 'masterUnmatchedOsmCheckbox', 'masterDisusedOsmCheckbox',
            'filterPlatform', 'filterOsmWay', 'filterOsmGroup', 'filterOsmTwoSided', 'filterDuplicatesOnly']
            .every(id => document.getElementById(id).checked)).toBe(true);
        expect(document.getElementById('filterIdentifier').checked).toBe(false);
        expect(activeFilters.station).toEqual(['8503000', 'way_45', '91-10-A-j26-1']);
        expect(activeFilters.routeDirections).toEqual(['', '', '0']);
        // A matched rule is a matched scope, so Top N stays.
        expect(activeFilters.topN).toBe(15);
        expect(window.filterUrlQuery()).toBe(query);
        expect(fetch.mock.calls.map(call => call[0])).toEqual([
            '/api/lookup?uic_ref=8503000', '/api/lookup?osm=way/45'
        ]);
    });

    test('Top N is dropped without a matched scope', () => {
        restoreFiltersFromUrl('?stop_filter=osm_unmatched&top_n=15');
        updateActiveFilters();

        expect(activeFilters.topN).toBeNull();
        expect(window.filterUrlQuery()).toBe('stop_filter=osm_unmatched');
    });

    test('a parent filter stands for its children, and Top N survives with the matched scope', () => {
        restoreFiltersFromUrl('?stop_filter=matched,atlas_unmatched&top_n=20');
        updateActiveFilters();

        expect(document.getElementById('filterIdentifier').checked).toBe(true);
        expect(document.getElementById('filterOSMNearby').checked).toBe(true);
        expect(window.filterUrlQuery()).toBe('stop_filter=matched,atlas_unmatched&top_n=20');
    });

    test('the address bar follows the filters once syncing is on, keeping the view and the stop', () => {
        history.replaceState({}, '', '/?sloid=ch:1:sloid:1&atlas_variant=x#map=15/47/8');
        document.getElementById('filterPlatform').checked = true;
        updateActiveFilters();
        expect(location.search).toBe('?sloid=ch:1:sloid:1&atlas_variant=x');

        enableFilterUrlSync();
        expect(location.search).toBe('?sloid=ch:1:sloid:1&atlas_variant=x&transport_types=platform');
        expect(location.hash).toBe('#map=15/47/8');

        document.getElementById('filterPlatform').checked = false;
        updateActiveFilters();
        expect(location.search).toBe('?sloid=ch:1:sloid:1&atlas_variant=x');
    });

    test('the route filter named by the variant parameters is not repeated as a search filter', () => {
        activeFilters.station = ['91-10-A-j26-1', '91-11-A-j26-1'];
        activeFilters.stationTypes = ['route', 'route'];
        activeFilters.routeDirections = ['', '1'];
        activeFilters.routeVariants = [{ atlas: 'a', osm: null, label: 'A' }, null];

        expect(window.filterUrlQuery()).toBe('search=route:91-11-A-j26-1+dir:1');
    });

    test('the Problems filter is restored from a link, written back and shown as chips', () => {
        window.restoreFiltersFromUrl('?problem_type=distance&priority=1,2');
        updateActiveFilters();

        expect(activeFilters.problemTypes).toEqual(['distance']);
        expect(activeFilters.problemPriorities).toEqual(['1', '2']);
        expect(window.filterUrlQuery()).toBe('problem_type=distance&priority=1,2');
        const chips = document.getElementById('activeFilters').textContent;
        expect(chips).toContain('Problem: Distance');
        expect(chips).toContain('Problem priority: P1');

        // Every type ticked is "all problems".
        document.getElementById('problemType-unmatched').checked = true;
        document.getElementById('problemType-unmatched').dispatchEvent(new Event('change', { bubbles: true }));
        updateActiveFilters();
        expect(activeFilters.problemTypes).toEqual(['all']);
        expect(document.getElementById('activeFilters').textContent).toContain('All problems');
    });

    test('a filter that is already applied is left alone, with a toast instead of an alert', () => {
        window.updateHeaderSummary = jest.fn();
        const notify = jest.spyOn(SharedUtils, 'notify').mockImplementation(() => {});

        expect(window.addSearchFilter('station', '8503000', '')).toBe(true);
        expect(window.addSearchFilter('station', '8503000', '')).toBe(false);
        expect(window.addSearchFilter('route', '91-10-A-j26-1', '0')).toBe(true);
        expect(window.addSearchFilter('route', '91-10-A-j26-1', '1')).toBe(true);

        expect(activeFilters.station).toEqual(['8503000', '91-10-A-j26-1', '91-10-A-j26-1']);
        expect(notify).toHaveBeenCalledTimes(1);
        expect(notify).toHaveBeenCalledWith('This filter is already applied.', 'info');
        notify.mockRestore();
    });

    test('notify shows text as text, then removes the toast', () => {
        jest.useFakeTimers();
        SharedUtils.notify('<b>No stop</b> found');
        const toast = document.querySelector('.temporary-message');
        expect(toast.textContent.trim()).toBe('<b>No stop</b> found');
        expect(toast.querySelector('b')).toBeNull();
        jest.runAllTimers();
        expect(document.querySelector('.temporary-message')).toBeNull();
        jest.useRealTimers();
    });

    test('restored stop filters are named from the public lookup', async () => {
        global.fetch = jest.fn(() => Promise.resolve({
            ok: true, json: () => Promise.resolve({ results: [{ source: { name: 'Zürich HB' }, osm: null }] })
        }));
        restoreFiltersFromUrl('?search=uic:8503000');
        await new Promise(resolve => setTimeout(resolve, 0));

        expect(document.getElementById('activeFilters').textContent).toContain('Zürich HB · UIC: 8503000');
    });
});
