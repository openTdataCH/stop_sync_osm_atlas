const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const PAGES = path.join(__dirname, '../../static/js/pages');

function stop(id, extra) {
    return Object.assign({
        id: 'p' + id,
        stop_id: id,
        problem: 'distance',
        priority: 2,
        sloid: 'ch:1:sloid:' + id,
        osm_node_id: String(1000 + id),
        atlas_lat: 46 + id / 1000,
        atlas_lon: 7,
        osm_lat: 46 + id / 1000,
        osm_lon: 7
    }, extra);
}

// A page of `count` stops, numbered from `first`.
function pageOfStops(first, count) {
    return Array.from({ length: count }, (_, index) => stop(first + index));
}

describe('Problems page permalinks', () => {
    let responses;

    function respondWith(data) {
        responses.push(data);
    }

    beforeAll(() => {
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/jquery-lite.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/shared/permalinks.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-utils.js'));
        loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-renderer.js'));
        ['problems-state', 'problems-data', 'problems-ui', 'problems-area', 'problems-permalink'].forEach(name => {
            loadBrowserScript(path.join(PAGES, name + '.js'));
        });
        window.$.getJSON = jest.fn((url, params, success) => {
            const data = responses.shift();
            success(typeof data === 'function' ? data(params) : data);
            return { fail: () => {} };
        });
        window.ProblemsMap = { renderProblem: jest.fn(), loadContextData: jest.fn(), clearContextData: jest.fn() };
    });

    beforeEach(() => {
        jest.useFakeTimers();
        responses = [];
        document.body.innerHTML = `
            <span id="problemTypeDisplay"></span><span id="problemPriorityDisplay"></span>
            <div id="actionButtonsContent"></div>
            <button id="prevProblemBtn"></button><button id="nextProblemBtn"></button>`;
        ProblemsState.resetPaginationState();
        ProblemsState.resetNavigationState();
        ProblemsState.setCurrentEntryProblems([]);
        ProblemsState.setSelectedProblemTypes([]);
        ProblemsState.setSelectedPriorities([]);
        ProblemsState.setSelectedAtlasOperators([]);
        ProblemsState.setShowContext(false);
        history.replaceState(null, '', '/problems');
    });

    afterEach(() => {
        jest.runOnlyPendingTimers();
        jest.useRealTimers();
    });

    test('reads filters and the linked stop, dropping unknown values', () => {
        expect(ProblemsPermalink.parse('?problem_type=unmatched,distance,bogus&priority=3,1,9&atlas_operator=SBB,BLS&osm=way/42')).toEqual({
            problemTypes: ['distance', 'unmatched'],
            priorities: ['1', '3'],
            atlasOperators: ['SBB', 'BLS'],
            area: null,
            focus: { sloid: null, osm_node_id: 'way_42' },
            invalidStop: false
        });
        expect(ProblemsPermalink.parse('?bbox=7.3,46.9,7.5,47').area).toEqual([7.3, 46.9, 7.5, 47]);
        expect(ProblemsPermalink.parse('?bbox=7.5,46.9,7.3,47').area).toBeNull();
        expect(ProblemsPermalink.parse('?bbox=7.3,46.9').area).toBeNull();

        const allTypes = ProblemsData.ALL_PROBLEM_TYPES.join(',');
        expect(ProblemsPermalink.parse('?problem_type=' + allTypes + '&sloid=ch:1:sloid:7&osm=node/7').problemTypes).toEqual([]);
        expect(ProblemsPermalink.parse('?sloid=ch:1:sloid:7&osm=node/7').focus).toEqual({ sloid: 'ch:1:sloid:7', osm_node_id: '7' });
        expect(ProblemsPermalink.parse('?osm=relation/7')).toMatchObject({ focus: null, invalidStop: true });
        expect(ProblemsPermalink.parse('')).toMatchObject({ problemTypes: [], priorities: [], atlasOperators: [], focus: null, invalidStop: false });
    });

    test('names an entry by its stop: both sides of a pair, one member of a duplicate group', () => {
        const params = ProblemsPermalink.entryStopParams;
        expect(params([stop(1)])).toEqual({ sloid: 'ch:1:sloid:1', osm: 'node/1001' });
        expect(params([stop(1, { osm_node_id: null })])).toEqual({ sloid: 'ch:1:sloid:1', osm: null });
        expect(params([stop(1, { sloid: null, osm_node_id: 'way_5' })])).toEqual({ sloid: null, osm: 'way/5' });
        expect(params([{ problem: 'duplicates', group_type: 'atlas', sloid: 'ch:1:sloid:a', members: [stop(2), stop(3)] }]))
            .toEqual({ sloid: 'ch:1:sloid:a' });
        expect(params([{ problem: 'duplicates', group_type: 'osm', members: [stop(2, { osm_node_id: '77' })] }]))
            .toEqual({ osm: 'node/77' });
        expect(params([])).toEqual({});

        const group = [{ problem: 'duplicates', members: [stop(2), stop(3, { osm_node_id: 'way_9' })] }];
        expect(ProblemsPermalink.entryMatchesFocus(group, { sloid: null, osm_node_id: 'way_9' })).toBe(true);
        expect(ProblemsPermalink.entryMatchesFocus([stop(1)], { sloid: 'ch:1:sloid:1', osm_node_id: '1001' })).toBe(true);
        expect(ProblemsPermalink.entryMatchesFocus([stop(1)], { sloid: 'ch:1:sloid:1', osm_node_id: '9' })).toBe(false);
    });

    test('keeps filters and the shown entry in the URL, and other parameters untouched', () => {
        history.replaceState(null, '', '/problems?utm=forum&sloid=old');
        ProblemsState.setSelectedProblemTypes(['distance', 'unmatched']);
        ProblemsState.setSelectedPriorities(['1']);
        ProblemsState.setSelectedAtlasOperators(['A & B']);
        respondWith({ problems: pageOfStops(1, 3), total: 3, page: 1 });

        ProblemsData.fetchProblems();

        expect(window.location.search).toBe(
            '?utm=forum&problem_type=distance,unmatched&priority=1&atlas_operator=A+%26+B&sloid=ch:1:sloid:1&osm=node/1001'
        );
        ProblemsData.navigateToNextProblem();
        expect(window.location.search).toContain('&sloid=ch:1:sloid:2&osm=node/1002');

        respondWith({ problems: [], total: 0, page: 1 });
        ProblemsState.resetPaginationState();
        ProblemsData.fetchProblems();
        expect(window.location.search).toBe('?utm=forum&problem_type=distance,unmatched&priority=1&atlas_operator=A+%26+B');
    });

    test('a linked stop opens on the page that holds it, numbered from that page', () => {
        respondWith(params => {
            expect(params).toMatchObject({ page: 1, focus_sloid: 'ch:1:sloid:250', focus_osm_node_id: '1250' });
            return { problems: pageOfStops(201, 100), total: 400, page: 3, focus_found: true };
        });
        const onFocusMissing = jest.fn();

        ProblemsData.fetchProblems(1, { focus: { sloid: 'ch:1:sloid:250', osm_node_id: '1250' }, onFocusMissing });

        expect(document.getElementById('problemTypeDisplay').textContent).toBe('Entry 250 of 400 · 1 Problem');
        expect(window.location.search).toBe('?sloid=ch:1:sloid:250&osm=node/1250');
        expect(onFocusMissing).not.toHaveBeenCalled();
        expect(document.getElementById('prevProblemBtn').disabled).toBe(false);
        expect(document.getElementById('nextProblemBtn').disabled).toBe(false);
    });

    test('Prev at the start of a linked window loads the page before; shown numbers stay', () => {
        const header = () => document.getElementById('problemTypeDisplay').textContent;
        respondWith({ problems: pageOfStops(201, 100), total: 400, page: 3, focus_found: true });
        ProblemsData.fetchProblems(1, { focus: { sloid: 'ch:1:sloid:201', osm_node_id: null } });
        expect(header()).toBe('Entry 201 of 400 · 1 Problem');

        // Page 2 holds a stop whose duplicate problem forms an extra entry.
        const page2 = pageOfStops(101, 100).concat([
            stop(150, { id: 'dup150', problem: 'duplicates', priority: 3, duplicate_group_sloids: 'g150' })
        ]);
        respondWith(params => {
            expect(params).toMatchObject({ page: 2 });
            expect(params.focus_sloid).toBeUndefined();
            return { problems: page2, total: 400, page: 2 };
        });
        ProblemsData.navigateToPreviousProblem();

        expect(ProblemsState.getFirstLoadedPage()).toBe(2);
        expect(header()).toBe('Group 200 of 400');
        expect(window.location.search).toBe('?sloid=ch:1:sloid:150&osm=node/1150');
        ProblemsData.navigateToPreviousProblem();
        expect(header()).toBe('Entry 199 of 400 · 1 Problem');
        expect(window.location.search).toBe('?sloid=ch:1:sloid:200&osm=node/1200');
        ProblemsData.navigateToNextProblem();
        ProblemsData.navigateToNextProblem();
        expect(header()).toBe('Entry 201 of 400 · 1 Problem');
        expect(window.location.search).toBe('?sloid=ch:1:sloid:201&osm=node/1201');
    });

    test('reaching page 1 numbers the list from its first entry', () => {
        respondWith({ problems: pageOfStops(101, 100), total: 300, page: 2, focus_found: true });
        ProblemsData.fetchProblems(1, { focus: { sloid: 'ch:1:sloid:101', osm_node_id: null } });
        respondWith({ problems: pageOfStops(1, 100), total: 300, page: 1 });

        ProblemsData.navigateToPreviousProblem();

        expect(ProblemsState.getFirstLoadedPage()).toBe(1);
        expect(document.getElementById('problemTypeDisplay').textContent).toBe('Entry 100 of 300 · 1 Problem');
        expect(window.location.search).toBe('?sloid=ch:1:sloid:100&osm=node/1100');
        ProblemsState.setCurrentProblemIndex(0);
        ProblemsUI.updateNavButtons();
        expect(document.getElementById('prevProblemBtn').disabled).toBe(true);
    });

    test('a later page keeps the window start; numbers and Next follow the total', () => {
        respondWith({ problems: pageOfStops(101, 100), total: 200, page: 2, focus_found: true });
        ProblemsData.fetchProblems(1, { focus: { sloid: 'ch:1:sloid:200', osm_node_id: null } });

        expect(document.getElementById('problemTypeDisplay').textContent).toBe('Entry 200 of 200 · 1 Problem');
        expect(ProblemsData.hasMorePages()).toBe(false);
        expect(document.getElementById('nextProblemBtn').disabled).toBe(true);
    });

    test('a stop without a problem under the filters falls back to the first entry', () => {
        respondWith({ problems: pageOfStops(1, 2), total: 2, page: 1, focus_found: false });
        const onFocusMissing = jest.fn();

        ProblemsData.fetchProblems(1, { focus: { sloid: 'ch:1:sloid:nope', osm_node_id: null }, onFocusMissing });

        expect(onFocusMissing).toHaveBeenCalledTimes(1);
        expect(window.location.search).toBe('?sloid=ch:1:sloid:1&osm=node/1001');
        expect(document.getElementById('prevProblemBtn').disabled).toBe(true);

        respondWith({ problems: [], total: 0, page: 1, focus_found: false });
        ProblemsState.resetPaginationState();
        ProblemsData.fetchProblems(1, { focus: { sloid: 'ch:1:sloid:nope', osm_node_id: null }, onFocusMissing });
        expect(onFocusMissing).toHaveBeenCalledTimes(2);
    });

    test('Copy link copies the address of the entry on screen', async () => {
        const writeText = jest.fn(() => Promise.resolve());
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        try {
            ProblemsState.setSelectedPriorities(['1']);
            respondWith({ problems: pageOfStops(1, 1), total: 1, page: 1 });
            ProblemsData.fetchProblems();
            document.body.insertAdjacentHTML('beforeend', '<button id="copy">Copy link</button>');

            await ProblemsPermalink.copyCurrentLink(document.getElementById('copy'));

            expect(writeText).toHaveBeenCalledWith('http://localhost/problems?priority=1&sloid=ch:1:sloid:1&osm=node/1001');
        } finally {
            delete navigator.clipboard;
            Permalinks.cancelCopyFeedback();
        }
    });
});
