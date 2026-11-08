const path = require('path');
const loadBrowserScript = require('./load-browser-script');

// /api/routes/variants for the S10, as the server answers it.
const HB = { key: '91-10-A-j26-1:0:Zürich HB', name: 'Uetliberg -> Zürich HB', direction_id: '0', stop_count: 9 };
const SELNAU = { key: '91-10-A-j26-1:0:Zürich Selnau', name: 'Uetliberg -> Zürich Selnau', direction_id: '0', stop_count: 8 };
const RELATION = { key: '1561015', name: 'Uetliberg -> Selnau', direction_id: '0', stop_count: 8 };
const BACK = { key: '1561012', name: 'Selnau -> Uetliberg', direction_id: '1', stop_count: 8 };
const variantsOfLine = {
    route_id: '91-10-A-j26-1', selected: null, bounds: null,
    variants: [
        { direction_id: '0', atlas: HB, osm: RELATION },
        { direction_id: '0', atlas: SELNAU, osm: null },
        { direction_id: '1', atlas: null, osm: BACK }
    ]
};
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const click = element => element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
const chip = () => document.querySelector('#activeFilters .direction-dropdown');

describe('route filter narrowed to variants', () => {
    beforeAll(() => {
        ['shared/jquery-lite', 'shared/utils', 'shared/permalinks', 'components/filter-chip-utils', 'pages/filters'].forEach(name => {
            loadBrowserScript(path.join(__dirname, '../../static/js/' + name + '.js'));
        });
        window.initFilterEventHandlers();
    });

    beforeEach(() => {
        document.body.innerHTML = '<div id="activeFilters"></div>';
        Object.assign(window.activeFilters, { station: [], stationTypes: [], routeDirections: [], routeVariants: [] });
        window.loadDataForViewport = jest.fn();
        window.updateHeaderSummary = jest.fn();
        window.fetch = global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(variantsOfLine) }));
        history.replaceState({}, '', '/?sloid=ch:1:sloid:7');
    });

    test('a variant link adds the route filter narrowed to its variants and keeps the address bar in step', () => {
        window.addRouteVariantFilter({ route_id: '91-10-A-j26-1', selected: { atlas: SELNAU, osm: RELATION } });

        expect(window.activeFilters.station).toEqual(['91-10-A-j26-1']);
        expect(JSON.parse(window.routeVariantsParam())).toEqual([{ atlas: SELNAU.key, osm: '1561015' }]);
        expect(chip().querySelector('.direction-current').textContent).toBe('Uetliberg → Zürich Selnau');
        expect(chip().querySelector('.direction-current').title).toBe('ATLAS: Uetliberg -> Zürich Selnau\nOSM: Uetliberg -> Selnau');
        expect(chip().getAttribute('data-current')).toBe('variant');
        // The other parameters stay as they were.
        expect(window.location.search).toBe('?sloid=ch:1:sloid:7&atlas_variant=91-10-A-j26-1:0:Z%C3%BCrich+Selnau&osm_variant=1561015');
        expect(window.loadDataForViewport).toHaveBeenCalled();
    });

    test('the dropdown lists the line\'s variants by direction, and choosing one or a direction narrows or widens the filter', async () => {
        window.filterByRoute('91-10-A-j26-1', '');
        expect(window.routeVariantsParam()).toBeNull();

        click(chip());
        await flush();
        expect(fetch).toHaveBeenCalledWith('/api/routes/variants?route_id=91-10-A-j26-1', expect.anything());
        const list = chip().querySelector('.direction-variants');
        // Each direction, then its variants: the name once, the OSM name below when it differs, the sources as tags.
        expect([...list.children].map(node => node.textContent)).toEqual([
            'Direction 0all variants', 'Uetliberg → Zürich HBOSM: Uetliberg → SelnauATLASOSM', 'Uetliberg → Zürich SelnauATLAS',
            'Direction 1all variants', 'Selnau → UetlibergOSM'
        ]);
        expect(list.querySelector('[data-variant="0"]').title).toBe('ATLAS: Uetliberg -> Zürich HB\nOSM: Uetliberg -> Selnau');
        // Only a heading is not an option: the list stays open.
        list.insertAdjacentHTML('beforeend', '<div class="direction-group">Other variants</div>');
        click(list.querySelector('.direction-group'));
        expect(chip().classList).toContain('open');

        click(list.querySelector('[data-variant="2"]'));
        expect(JSON.parse(window.routeVariantsParam())).toEqual([{ atlas: null, osm: '1561012' }]);
        expect(window.location.search).toBe('?sloid=ch:1:sloid:7&osm_variant=1561012');

        click(chip());
        await flush();
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(chip().querySelector('.direction-current').textContent).toBe('Selnau → Uetliberg · OSM only');
        expect(chip().querySelector('.is-current').getAttribute('data-variant')).toBe('2');
        click(chip().querySelector('.direction-option[data-direction="1"]'));
        expect(window.activeFilters.routeDirections).toEqual(['1']);
        expect(window.routeVariantsParam()).toBeNull();
        expect(window.location.search).toBe('?sloid=ch:1:sloid:7');
    });

    test('removing the route filter drops its variants from the address bar', () => {
        window.addRouteVariantFilter({ route_id: '91-10-A-j26-1', selected: { atlas: HB, osm: null } });
        expect(window.location.search).toContain('atlas_variant=');
        click(document.querySelector('#activeFilters .remove-filter'));
        expect(window.activeFilters.routeVariants).toEqual([]);
        expect(window.location.search).toBe('?sloid=ch:1:sloid:7');
    });
});
