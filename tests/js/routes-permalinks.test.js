const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const MATCHED_ATLAS = '91-10-A-j26-1:0:Zürich HB';

function panel(attributes, label) {
    return `
        <details class="route-card__panel route-card__panel--map" ${attributes}>
          <summary>${label}</summary>
          <div class="route-card__panel-content">
            <div class="route-card__panel-actions">
              <button type="button" class="route-copy-link"><i class="fas fa-link"></i> Copy link</button>
            </div>
          </div>
        </details>`;
}

// Loads routes.js as the page does, after the server rendered the cards.
function openPage(url) {
    history.replaceState(null, '', url);
    document.body.innerHTML = [
        panel(`data-atlas-variant="${MATCHED_ATLAS}" data-osm-variant="2169538"`, 'matched'),
        panel('data-atlas-variant="91-10-A-j26-1:1:Selnau"', 'unmatched ATLAS'),
        panel('data-osm-variant="999"', 'unmatched OSM'),
        '<details class="route-card__panel route-card__panel--map"><summary>no ids</summary></details>'
    ].join('');
    loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes.js'));
    return Array.from(document.querySelectorAll('details'));
}

function toggle(details, open) {
    details.open = open;
    details.dispatchEvent(new Event('toggle'));
}

describe('Routes variant permalinks', () => {
    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/components/filter-chip-utils.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
        Element.prototype.scrollIntoView = jest.fn();
    });

    beforeEach(() => {
        window.routesPageConfig = { selectedAtlasOperators: [], selectedOsmOperators: [], baseUrl: '/routes' };
    });

    afterEach(() => {
        window.dispatchEvent(new Event('pagehide'));
        history.replaceState(null, '', '/');
    });

    test('a linked variant is opened and scrolled into view', () => {
        const [, , osmOnly] = openPage('/routes?page=2&osm_variant=999');

        expect(osmOnly.open).toBe(true);
        expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: 'start' });
        toggle(osmOnly, true);
        expect(window.location.search).toBe('?page=2&osm_variant=999');
    });

    test('a matched variant needs both identifiers to match', () => {
        const [matched] = openPage('/routes?atlas_variant=' + encodeURIComponent(MATCHED_ATLAS) + '&osm_variant=2169538');
        expect(matched.open).toBe(true);
    });

    test('the URL names the most recently opened variant, encoded as the server does', () => {
        const [matched, atlasOnly] = openPage('/routes?per_page=20&matched=unmatched&q=10');
        const length = history.length;

        toggle(atlasOnly, true);
        expect(window.location.search).toBe('?per_page=20&matched=unmatched&q=10&atlas_variant=91-10-A-j26-1%3A1%3ASelnau');
        toggle(matched, true);
        expect(window.location.search).toBe(
            '?per_page=20&matched=unmatched&q=10&atlas_variant=91-10-A-j26-1%3A0%3AZ%C3%BCrich+HB&osm_variant=2169538'
        );
        toggle(matched, false);
        expect(window.location.search).toBe('?per_page=20&matched=unmatched&q=10&atlas_variant=91-10-A-j26-1%3A1%3ASelnau');
        toggle(atlasOnly, false);
        expect(window.location.search).toBe('?per_page=20&matched=unmatched&q=10');
        expect(history.length).toBe(length);
    });

    test('a variant that is not on the page is dropped from the URL with a notice', () => {
        const message = jest.spyOn(SharedUtils, 'showTemporaryMessage').mockImplementation(() => {});
        try {
            const panels = openPage('/routes?page=3&osm_variant=123');

            expect(panels.some(details => details.open)).toBe(false);
            expect(window.location.search).toBe('?page=3');
            expect(message).toHaveBeenCalledWith(expect.stringContaining('not in this list'), 'warning', 6000);
        } finally {
            message.mockRestore();
        }
    });

    test('Copy link copies the page address naming that variant', async () => {
        const writeText = jest.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        jest.useFakeTimers();
        try {
            const [, , osmOnly] = openPage('/routes/non-gtfs?page=2');

            osmOnly.querySelector('.route-copy-link').click();
            await Promise.resolve();
            await Promise.resolve();

            expect(writeText).toHaveBeenCalledWith('http://localhost/routes/non-gtfs?page=2&osm_variant=999');
            expect(osmOnly.querySelector('.route-copy-link').textContent.trim()).toBe('Copied');
        } finally {
            delete navigator.clipboard;
            Permalinks.cancelCopyFeedback();
            jest.useRealTimers();
        }
    });
});
