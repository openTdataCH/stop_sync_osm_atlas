const path = require('path');
const loadBrowserScript = require('./load-browser-script');

describe('Problems area filter', () => {
    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/pages/problems-area.js'));
    });

    test('an area is west,south,east,north, rounded to about a metre', () => {
        const bounds = { getWest: () => 7.3000004, getSouth: () => 46.912345678, getEast: () => 7.5, getNorth: () => 47 };
        const area = ProblemsArea.boundsToArea(bounds);

        expect(area).toEqual([7.3, 46.91235, 7.5, 47]);
        expect(ProblemsArea.formatArea(area)).toBe('7.3,46.91235,7.5,47');
        expect(ProblemsArea.formatArea(null)).toBe('');
        expect(ProblemsArea.parseArea('7.3,46.91235,7.5,47')).toEqual(area);
    });

    test.each(['', '7.3,46.9,7.5', '7.5,46.9,7.3,47', '7.3,47,7.5,46.9', 'a,b,c,d', '7.3,46.9,7.5,91'])(
        '%p is not an area', text => {
            expect(ProblemsArea.parseArea(text)).toBeNull();
        });

    test('the Problems map shows the area as an outline, and none without one', () => {
        const added = [];
        const removed = jest.fn();
        window.AppConstants = { COLORS: { MATCHED: '#174092' } };
        window.L = global.L = {
            latLngBounds: (a, b) => [a, b],
            rectangle: jest.fn((bounds, style) => ({ bounds, style, addTo() { added.push(this); return this; }, remove: removed }))
        };

        ProblemsArea.showOutline({}, [7.3, 46.9, 7.5, 47]);
        expect(added[0].bounds).toEqual([[46.9, 7.3], [47, 7.5]]);
        expect(added[0].style).toMatchObject({ dashArray: '6,4', fill: false, interactive: false });

        ProblemsArea.showOutline({}, null);
        expect(removed).toHaveBeenCalledTimes(1);
        expect(added).toHaveLength(1);
    });

    describe('the dialog', () => {
        let mapHandlers;
        let onApply;
        const apply = () => document.getElementById('areaApplyBtn');
        const clear = () => document.getElementById('areaClearBtn');
        const click = latlng => mapHandlers.click({ latlng });

        beforeEach(() => {
            document.body.innerHTML = `
                <div id="areaModal"></div><div id="areaMap"></div>
                <button id="areaClearBtn"></button><button id="areaApplyBtn"></button>`;
            mapHandlers = {};
            onApply = jest.fn();
            const bounds = (a, b) => ({
                getWest: () => Math.min(a.lng, b.lng), getEast: () => Math.max(a.lng, b.lng),
                getSouth: () => Math.min(a.lat, b.lat), getNorth: () => Math.max(a.lat, b.lat)
            });
            window.L = global.L = {
                latLngBounds: (a, b) => (Array.isArray(a) ? bounds({ lat: a[0], lng: a[1] }, { lat: b[0], lng: b[1] }) : bounds(a, b)),
                rectangle: jest.fn(() => ({ addTo() { return this; }, remove: jest.fn(), setBounds: jest.fn() }))
            };
            window.AppConstants = { COLORS: { MATCHED: '#174092' }, MAP: { DEFAULT_CENTER: [46.8, 8.2], DEFAULT_ZOOM: 8, MAX_ZOOM: 19 } };
            window.MapShared = { createBaseTileLayers: () => ({}) };
            window.MapComponents = { MapCore: { create: () => ({ map: { on: (name, fn) => { mapHandlers[name] = fn; } } }) } };
            window.bootstrap = global.bootstrap = { Modal: { getOrCreateInstance: () => ({ show: jest.fn(), hide: jest.fn() }) } };
            // A fresh copy, so each test starts without a picker.
            loadBrowserScript(path.join(__dirname, '../../static/js/pages/problems-area.js'));
        });

        test('without an area, apply waits for a rectangle and clearing wipes it', () => {
            ProblemsArea.open(null, null, onApply);
            expect(apply().disabled).toBe(true);
            expect(apply().textContent).toBe('Filter problems in this area');
            expect(clear().disabled).toBe(true);

            click({ lat: 46.9, lng: 7.3 });
            expect(clear().disabled).toBe(false);
            expect(apply().disabled).toBe(true);
            click({ lat: 47, lng: 7.5 });
            expect(apply().disabled).toBe(false);

            clear().click();
            expect(apply().disabled).toBe(true);
            expect(clear().disabled).toBe(true);

            click({ lat: 46.9, lng: 7.3 });
            click({ lat: 47, lng: 7.5 });
            apply().click();
            expect(onApply).toHaveBeenCalledWith([7.3, 46.9, 7.5, 47]);
        });

        test('with an area applied, clearing the selection turns apply into removing it', () => {
            ProblemsArea.open([7.3, 46.9, 7.5, 47], null, onApply);
            expect(apply().disabled).toBe(false);
            expect(clear().disabled).toBe(false);

            clear().click();
            expect(apply().disabled).toBe(false);
            expect(apply().textContent).toBe('Show all problems');

            apply().click();
            expect(onApply).toHaveBeenCalledWith(null);
        });
    });
});
