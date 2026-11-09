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
});
