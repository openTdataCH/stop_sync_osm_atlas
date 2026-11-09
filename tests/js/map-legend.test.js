const path = require('path');
const loadBrowserScript = require('./load-browser-script');

describe('map legend', () => {
    let added;

    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/components/map-legend.js'));
    });

    beforeEach(() => {
        localStorage.clear();
        document.body.innerHTML = '';
        added = null;
        window.L = global.L = {
            control: jest.fn(options => ({
                options,
                addTo(map) { added = this.onAdd(map); document.body.appendChild(added); return this; }
            })),
            DomUtil: { create: (tag, className) => Object.assign(document.createElement(tag), { className }) },
            DomEvent: { disableClickPropagation: jest.fn(), disableScrollPropagation: jest.fn() }
        };
        window.matchMedia = jest.fn(() => ({ matches: false }));
    });

    test('names the source and explains colours, rings, lines and letters', () => {
        const html = MapLegend.contentHtml('City & Transit');

        expect(html).toContain('Matched City &amp; Transit stop');
        expect(html).toContain('OSM stop without City &amp; Transit match');
        expect(html).toContain('map-legend__marker--disused');
        expect(html).toContain('Parts of one OSM stop');
        expect(html).toContain('<b>D</b> City &amp; Transit duplicate');
    });

    test('opens on a first visit to a wide screen and remembers when it is closed', () => {
        MapLegend.add({}, { sourceLabel: 'ATLAS' });
        expect(L.control).toHaveBeenCalledWith({ position: 'bottomleft' });
        expect(added.classList.contains('is-open')).toBe(true);

        const toggle = added.querySelector('.map-legend__toggle');
        toggle.click();
        expect(added.classList.contains('is-open')).toBe(false);
        expect(toggle.getAttribute('aria-expanded')).toBe('false');

        MapLegend.add({}, { sourceLabel: 'ATLAS' });
        expect(added.classList.contains('is-open')).toBe(false);
    });

    test('starts closed on a narrow screen', () => {
        window.matchMedia = jest.fn(() => ({ matches: true }));
        MapLegend.add({}, {});

        expect(added.classList.contains('is-open')).toBe(false);
    });
});
