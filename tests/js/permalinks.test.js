const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const LIMITS = { minZoom: 8, maxZoom: 20, maxBounds: [[45.5, 5.5], [48, 11]] };

// Enough of a Leaflet map to dispatch moveend/popupopen/popupclose.
function createMap() {
    const handlers = {};
    const map = {
        zoom: 14,
        center: { lat: 47.3769, lng: 8.5417 },
        on: jest.fn((name, handler) => { (handlers[name] = handlers[name] || []).push(handler); }),
        off: jest.fn((name, handler) => { handlers[name] = (handlers[name] || []).filter(h => h !== handler); }),
        fire: (name, event) => (handlers[name] || []).slice().forEach(handler => handler(event || {})),
        getZoom: () => map.zoom,
        getCenter: () => ({ lat: map.center.lat, lng: map.center.lng }),
        setView: jest.fn((center, zoom) => {
            map.center = { lat: center[0], lng: center[1] };
            map.zoom = zoom;
        })
    };
    return map;
}

function popupWithButton(type, ref) {
    const element = document.createElement('div');
    element.innerHTML = `<button class="popup-copy-link" data-permalink-type="${type}" data-permalink-ref="${ref}">Copy link</button>`;
    return { getElement: () => element };
}

async function flushPromises() {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

describe('Permalinks', () => {
    beforeAll(() => {
        window.AppConstants = { MAP: { MIN_ZOOM: 8, MAX_ZOOM: 20, MAX_BOUNDS: LIMITS.maxBounds } };
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
    });

    beforeEach(() => {
        jest.useFakeTimers();
    });

    afterEach(() => {
        Permalinks.cancelCopyFeedback();
        jest.runOnlyPendingTimers();
        jest.useRealTimers();
        history.replaceState(null, '', '/');
        document.body.innerHTML = '';
    });

    test('parses and formats the openstreetmap.org #map= hash', () => {
        expect(Permalinks.parseMapHash('#map=15/46.94809/7.44744')).toEqual({ center: [46.94809, 7.44744], zoom: 15 });
        expect(Permalinks.parseMapHash('#map=12/47/8&layers=T')).toEqual({ center: [47, 8], zoom: 12 });
        expect(Permalinks.parseMapHash('#map=5/47/8', { minZoom: 2 })).toEqual({ center: [47, 8], zoom: 5 });
        expect(Permalinks.formatMapHash(15, 46.948091234, 7.4474449)).toBe('#map=15/46.94809/7.44744');
        expect(Permalinks.formatMapHash(9, 47.1, 8)).toBe('#map=9/47.1/8');

        [
            '#map=21/47/8', '#map=7/47/8',           // outside MIN/MAX_ZOOM
            '#map=12/52.5/13.4', '#map=12/47/-8',    // outside MAX_BOUNDS
            '#map=12/47', '#map=a/b/c', '#map=12/1e1/8', '#map=12/47/8/9', '#foo', '#', ''
        ].forEach(hash => expect(Permalinks.parseMapHash(hash)).toBeNull());
    });

    test('encodes values like the server canonical URLs: readable "/", ":" and ","', () => {
        expect(Permalinks.encodeParams({ sloid: 'ch:1:sloid:7000', osm: 'way/4', empty: '', none: null }))
            .toBe('sloid=ch:1:sloid:7000&osm=way/4');
        expect(Permalinks.encodeParams({ problem_type: 'distance,unmatched', atlas_operator: 'A & B' }))
            .toBe('problem_type=distance,unmatched&atlas_operator=A+%26+B');
        // /routes canonicalises with safe=',' only, like urlencode(safe=',').
        expect(Permalinks.encodeParams({ atlas_variant: "91-10-A-j26-1:0:Zürich (HB)*!'" }, ','))
            .toBe('atlas_variant=91-10-A-j26-1%3A0%3AZ%C3%BCrich+%28HB%29%2A%21%27');
        expect(Permalinks.encodeParams(null)).toBe('');
    });

    test('rewrites only the named parameters and keeps the others byte for byte', () => {
        const others = '?atlas_operator=EX&osm_operator=Example+%26+Co&osm_operator_wikidata=Q1%2CQ2';
        expect(Permalinks.buildSearch(others + '&sloid=old', ['sloid', 'osm'], 'osm=node/1'))
            .toBe(others + '&osm=node/1');
        expect(Permalinks.buildSearch(others + '&s%6Coid=old', ['sloid'], '')).toBe(others);
        expect(Permalinks.buildSearch('?bad=%E0%A4%A&sloid=1', ['sloid'], '')).toBe('?bad=%E0%A4%A');
        expect(Permalinks.buildSearch('', ['sloid'], '')).toBe('');
    });

    test('replaces the URL in place, without a history entry, only when it changes', () => {
        history.replaceState(null, '', '/?a=1#map=9/47/8');
        const length = history.length;

        expect(Permalinks.replaceUrl({ search: '?a=1' })).toBe(false);
        expect(Permalinks.replaceUrl({ search: '?a=2' })).toBe(true);
        expect(Permalinks.replaceUrl({ hash: '#map=10/47/8' })).toBe(true);

        expect(window.location.search + window.location.hash).toBe('?a=2#map=10/47/8');
        expect(history.length).toBe(length);
        expect(Permalinks.pageUrl('?x=1', '#map=1/2/3')).toBe('http://localhost/?x=1#map=1/2/3');
    });

    test('starts at a usable hash view and otherwise at the default', () => {
        const fallback = { center: [47, 8], zoom: 14 };
        history.replaceState(null, '', '/#map=16/46.9/7.4');
        expect(Permalinks.initialMapView(fallback, LIMITS)).toEqual({ center: [46.9, 7.4], zoom: 16 });
        history.replaceState(null, '', '/#map=16/60/7.4');
        expect(Permalinks.initialMapView(fallback, LIMITS)).toBe(fallback);
    });

    test('writes the view once per burst of moves and follows an edited hash', () => {
        const map = createMap();
        const binding = Permalinks.bindMapHash(map, LIMITS);
        map.center = { lat: 46.948091234, lng: 7.4474449 };
        map.zoom = 15;

        map.fire('moveend');
        map.fire('moveend');
        expect(window.location.hash).toBe('');
        jest.advanceTimersByTime(Permalinks.HASH_DEBOUNCE_MS);
        expect(window.location.hash).toBe('#map=15/46.94809/7.44744');
        expect(map.setView).not.toHaveBeenCalled();

        history.replaceState(null, '', '/#map=12/46.9/7.4');
        window.dispatchEvent(new Event('hashchange'));
        expect(map.setView).toHaveBeenCalledWith([46.9, 7.4], 12);

        history.replaceState(null, '', '/#');
        window.dispatchEvent(new Event('hashchange'));
        expect(window.location.hash).toBe('#map=12/46.9/7.4');

        binding.destroy();
        map.fire('moveend');
        window.dispatchEvent(new Event('hashchange'));
        expect(jest.getTimerCount()).toBe(0);
        expect(map.setView).toHaveBeenCalledTimes(1);
    });

    test('names the most recently opened item that is still open', () => {
        history.replaceState(null, '', '/?keep=1');
        const tracker = Permalinks.createSelectionTracker(['sloid', 'osm']);
        const first = {};
        const second = {};

        expect(tracker.open(first, 'sloid=a')).toBe(true);
        expect(tracker.open(second, 'osm=node/2')).toBe(true);
        expect(window.location.search).toBe('?keep=1&osm=node/2');
        expect(tracker.open({}, '')).toBe(false);
        expect(tracker.close({})).toBe(false);

        tracker.close(second);
        expect(window.location.search).toBe('?keep=1&sloid=a');
        tracker.open(second, 'osm=node/2');
        tracker.open(first, 'sloid=a');
        expect(window.location.search).toBe('?keep=1&sloid=a');
        tracker.close(first);
        tracker.close(second);
        expect(window.location.search).toBe('?keep=1');
    });

    test('follows popups through their first Copy link button', () => {
        const map = createMap();
        const binding = Permalinks.trackPopups(map, ['sloid'], popup => {
            const button = Permalinks.popupCopyButton(popup);
            return button ? 'sloid=' + button.getAttribute('data-permalink-ref') : null;
        });
        const popup = popupWithButton('atlas', 'ch:1:sloid:1');

        map.fire('popupopen', { popup });
        expect(window.location.search).toBe('?sloid=ch:1:sloid:1');
        map.fire('popupopen', { popup: { getElement: () => document.createElement('div') } });
        expect(window.location.search).toBe('?sloid=ch:1:sloid:1');
        map.fire('popupclose', { popup });
        expect(window.location.search).toBe('');

        binding.destroy();
        map.fire('popupopen', { popup });
        expect(window.location.search).toBe('');
        expect(Permalinks.popupCopyButton(null)).toBeNull();
    });

    test('copies with the Clipboard API and confirms briefly', async () => {
        const writeText = jest.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        try {
            document.body.innerHTML = '<button><i class="fas fa-link"></i> Copy link</button>';
            const button = document.querySelector('button');

            await expect(Permalinks.copyLink(button, 'http://localhost/?a=1')).resolves.toBe(true);
            expect(writeText).toHaveBeenCalledWith('http://localhost/?a=1');
            expect(button.textContent.trim()).toBe('Copied');
            expect(button.classList.contains('is-copied')).toBe(true);

            jest.advanceTimersByTime(Permalinks.COPIED_FEEDBACK_MS);
            expect(button.textContent.trim()).toBe('Copy link');
            expect(button.classList.contains('is-copied')).toBe(false);
        } finally {
            delete navigator.clipboard;
        }
    });

    test('falls back to a selection copy, and shows the link when copying is impossible', async () => {
        const message = jest.spyOn(SharedUtils, 'showTemporaryMessage').mockImplementation(() => {});
        document.body.innerHTML = '<button>Copy link</button>';
        const button = document.querySelector('button');
        try {
            document.execCommand = jest.fn(() => true);
            await expect(Permalinks.copyLink(button, 'http://localhost/?a=1')).resolves.toBe(true);
            expect(document.execCommand).toHaveBeenCalledWith('copy');
            expect(document.querySelector('textarea')).toBeNull();

            Permalinks.cancelCopyFeedback();
            document.execCommand = jest.fn(() => { throw new Error('blocked'); });
            await expect(Permalinks.copyLink(button, 'http://localhost/?a=<1>')).resolves.toBe(false);
            await flushPromises();
            expect(button.textContent).toBe('Copy link');
            expect(message).toHaveBeenCalledWith(expect.stringContaining('?a=&lt;1&gt;'), 'warning', 8000);
        } finally {
            delete document.execCommand;
            message.mockRestore();
        }
    });
});
