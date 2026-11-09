const path = require('path');
const loadBrowserScript = require('./load-browser-script');

const ZURICH = { kind: 'station', value: '8503000', ref: '8503000', name: 'Zürich HB', side: 'source', matched_name: null, stops: 24 };
const OSM = { kind: 'osm', value: 'way_4', ref: 'way/4', name: '<b>Alte</b>', side: 'osm', matched_name: null, stop_type: 'osm_disused' };
const ALIAS = { ...ZURICH, matched_name: 'Zürich Hauptbahnhof' };

function key(name) {
    return new KeyboardEvent('keydown', { key: name, cancelable: true });
}

describe('search suggestions', () => {
    let input, list, onPick, load, suggest;

    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/components/search-suggest.js'));
    });

    beforeEach(() => {
        jest.useFakeTimers();
        document.body.innerHTML = '<input id="q"><ul id="s" class="d-none"></ul>';
        input = document.getElementById('q');
        list = document.getElementById('s');
        onPick = jest.fn();
        load = jest.fn(() => Promise.resolve([ZURICH, OSM]));
        suggest = SearchSuggest.attach({ input, list, onPick, fetch: load, preselectFirst: () => true });
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    async function type(text) {
        input.value = text;
        input.dispatchEvent(new Event('input'));
        jest.advanceTimersByTime(150);
        await Promise.resolve();
        await Promise.resolve();
    }

    function options() {
        return Array.from(list.querySelectorAll('[role="option"]'));
    }

    test('lists names, numbers and sources as text, with the first preselected', async () => {
        await type('zu');

        expect(load).toHaveBeenCalledWith('zu');
        expect(list.classList.contains('d-none')).toBe(false);
        expect(input.getAttribute('aria-expanded')).toBe('true');
        expect(input.getAttribute('aria-activedescendant')).toBe('s-0');
        expect(options().map(option => option.textContent)).toEqual([
            'Zürich HB8503000ATLAS · 24 platforms',
            '<b>Alte</b>way/4OSM · disused'
        ]);
        expect(list.querySelector('b')).toBeNull();
        expect(options()[0].getAttribute('aria-selected')).toBe('true');
    });

    test('waits for two characters and for a pause in typing', async () => {
        input.value = 'z';
        input.dispatchEvent(new Event('input'));
        jest.advanceTimersByTime(500);
        input.value = 'zu';
        input.dispatchEvent(new Event('input'));
        input.value = 'zur';
        input.dispatchEvent(new Event('input'));
        jest.advanceTimersByTime(150);

        expect(load.mock.calls).toEqual([['zur']]);
    });

    test('arrow keys move the choice and Enter picks it', async () => {
        await type('zu');

        expect(suggest.handleKeydown(key('ArrowDown'))).toBe(true);
        expect(input.getAttribute('aria-activedescendant')).toBe('s-1');
        suggest.handleKeydown(key('ArrowDown'));
        expect(input.getAttribute('aria-activedescendant')).toBe('s-0');
        suggest.handleKeydown(key('ArrowUp'));
        const enter = key('Enter');
        expect(suggest.handleKeydown(enter)).toBe(true);

        expect(enter.defaultPrevented).toBe(true);
        expect(onPick).toHaveBeenCalledWith(OSM);
        expect(list.classList.contains('d-none')).toBe(true);
    });

    test('typing on drops the choice, so Enter never picks from older text', async () => {
        await type('hauptbahnhof');
        input.value = 'hauptbahnhof s';
        input.dispatchEvent(new Event('input'));

        expect(options()).toHaveLength(2);
        expect(input.hasAttribute('aria-activedescendant')).toBe(false);
        expect(suggest.handleKeydown(key('Enter'))).toBe(false);
        expect(onPick).not.toHaveBeenCalled();
        suggest.close();  // cancels the pending request for the new text
    });

    test('a click picks a suggestion and Escape closes the list', async () => {
        await type('zu');
        options()[0].querySelector('.search-suggestion__ref').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        expect(onPick).toHaveBeenCalledWith(ZURICH);

        await type('zur');
        expect(suggest.handleKeydown(key('Escape'))).toBe(true);
        expect(options()).toHaveLength(0);
        expect(suggest.handleKeydown(key('Enter'))).toBe(false);
    });

    test('Enter is left to the caller when nothing is preselected', async () => {
        suggest = SearchSuggest.attach({ input, list, onPick, fetch: load, preselectFirst: () => false });
        await suggest.request('8503000');

        expect(input.hasAttribute('aria-activedescendant')).toBe(false);
        expect(suggest.handleKeydown(key('Enter'))).toBe(false);
        expect(onPick).not.toHaveBeenCalled();
    });

    test('an older response never replaces a newer one', async () => {
        let resolveOld;
        load.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
        const old = suggest.request('zu');
        const latest = suggest.request('zur');
        resolveOld([OSM]);

        await expect(old).resolves.toBeNull();
        await expect(latest).resolves.toEqual([ZURICH, OSM]);
        expect(options()).toHaveLength(2);
    });

    test('a closed list stays closed when a response arrives late', async () => {
        let resolveLate;
        load.mockImplementationOnce(() => new Promise(resolve => { resolveLate = resolve; }));
        const late = suggest.request('zu');
        suggest.close();
        resolveLate([ZURICH]);

        await expect(late).resolves.toBeNull();
        expect(list.classList.contains('d-none')).toBe(true);
    });

    test('names the OSM name a station was found under', async () => {
        load.mockResolvedValueOnce([ALIAS]);
        await suggest.request('hauptbahnhof');

        expect(list.querySelector('.search-suggestion__other').textContent).toBe('OSM name: Zürich Hauptbahnhof');
    });

    test('describes sources and OSM states', () => {
        expect(SearchSuggest.describe({ side: 'source', stops: 1 })).toBe('ATLAS · 1 platform');
        expect(SearchSuggest.describe({ side: 'osm', stop_type: 'osm_unmatched' })).toBe('OSM · no match');
    });

    test('fetches suggestions from the search endpoint', async () => {
        const fetchMock = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [ZURICH] }) }));
        global.fetch = fetchMock;

        await expect(SearchSuggest.fetchSuggestions('zürich hb')).resolves.toEqual([ZURICH]);
        expect(fetchMock.mock.calls[0][0]).toBe('/api/search/suggest?q=z%C3%BCrich%20hb');

        global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 503 }));
        await expect(SearchSuggest.fetchSuggestions('zu')).rejects.toThrow('HTTP 503');
        delete global.fetch;
    });
});

describe('map search box', () => {
    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/jquery-lite.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/components/filter-chip-utils.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/pages/filters.js'));
    });

    test('dashed text may be a stop name, so only route: is an identifier for sure', () => {
        expect(parseSmartSearchInput('Saint-Imier')).toMatchObject({ kind: 'route', implicit: true });
        expect(parseSmartSearchInput('route:11-T-j25-1')).toMatchObject({ kind: 'route', implicit: false });
        expect(window.shouldPreselectSuggestion('Zürich HB')).toBe(true);
        expect(window.shouldPreselectSuggestion('Saint-Imier')).toBe(true);
        expect(window.shouldPreselectSuggestion('8503000')).toBe(false);
        expect(window.shouldPreselectSuggestion('node/123')).toBe(false);
    });

    test('Enter on a name picks the best suggestion, and an unknown name says so', async () => {
        document.body.innerHTML = '<div id="activeFilters"></div><input id="smartSearchInput">'
            + '<ul id="smartSearchSuggestions" class="d-none"></ul>'
            + '<div id="smartSearchHint" class="d-none"></div><div id="smartSearchError" class="d-none"></div>';
        activeFilters.station = [];
        activeFilters.stationTypes = [];
        activeFilters.routeDirections = [];
        activeFilters.routeVariants = [];
        window.fetchAndCenterSpecificStop = jest.fn(() => Promise.resolve({ stop: {} }));
        window.loadDataForViewport = jest.fn();
        window.updateHeaderSummary = jest.fn();
        global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [ZURICH] }) }));
        window.initSearchSuggestions();
        const input = document.getElementById('smartSearchInput');
        const flush = () => new Promise(resolve => setTimeout(resolve, 0));

        input.value = 'zurich hb';
        window.submitSmartSearch();
        await flush();

        expect(window.fetchAndCenterSpecificStop).toHaveBeenCalledWith('8503000', 'station');
        expect(input.value).toBe('');
        expect(activeFilters.station).toEqual(['8503000']);
        expect(document.getElementById('activeFilters').textContent).toContain('Zürich HB · UIC: 8503000');

        global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [] }) }));
        input.value = 'Nowhere';
        window.submitSmartSearch();
        await flush();

        const error = document.getElementById('smartSearchError');
        expect(error.classList.contains('d-none')).toBe(false);
        expect(error.textContent).toContain('No stop found named "Nowhere".');
        expect(input.value).toBe('Nowhere');
        delete global.fetch;
    });

    test('chips name the stop a search filter keeps', () => {
        document.body.innerHTML = '<div id="activeFilters"></div>';
        activeFilters.station = ['8503000', '123'];
        activeFilters.stationTypes = ['station', 'osm'];
        activeFilters.routeDirections = ['', ''];
        activeFilters.routeVariants = [null, null];
        window.searchTokenNames['station:8503000'] = 'Zürich HB';

        updateFiltersUI();

        const text = document.getElementById('activeFilters').textContent;
        expect(text).toContain('Zürich HB · UIC: 8503000');
        expect(text).toContain('OSM Node ID: 123');
        expect(window.searchTokenNameFromStop('osm', { osm_name: 'Bahnhof' })).toBe('Bahnhof');
        expect(window.searchTokenNameFromStop('atlas', { atlas_designation_official: 'Bern' })).toBe('Bern');
        expect(window.searchTokenNameFromStop('route', {})).toBe('');
    });
});
