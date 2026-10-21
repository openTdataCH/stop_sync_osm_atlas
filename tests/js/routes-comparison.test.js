const path = require('path');
const loadBrowserScript = require('./load-browser-script');

const candidate = (id, score, name = 'Line 10', isMatched = false) => ({
  id, route_id: '10', route_name: name, display_name: 'Central → Lake', direction_id: '0',
  source_itinerary_id: '9' + id, percentage: score, stop_ratio: score / 100,
  matched_stop_count: score / 20, is_matched: isMatched
});
const osmBest = candidate('301', 80, 'OSM best', true);
const osmLower = candidate('302', 60, 'OSM alternative');
const osmLast = candidate('303', 0, 'OSM last');
const atlasBest = candidate('401', 100, 'ATLAS best');
const atlasLower = candidate('402', 40, 'ATLAS alternative');
const stop = (id, position = 1, label = id) => ({
  id, position, stop_sequence: position * 2, stop_label: label, stop_ids: [id], uic_ref: null, lat: 47, lon: 8
});
const pair = (index, matchType = 'resolved_sloid_match') => ({
  atlas: stop('a' + index, index), osm: stop('o' + index, index), match_type: matchType
});
const result = (atlasId = '101', osmId = '301', changes = {}) => ({
  atlas: { ...candidate(atlasId, 80), id: atlasId }, osm: { ...candidate(osmId, 80), id: osmId },
  matched_stop_count: 4, atlas_stop_count: 5, osm_stop_count: 4,
  stop_ratio: 0.8, percentage: 80, direction_status: 'match', is_saved_match: false,
  rows: [pair(1), { atlas: stop('a-gap', 2), osm: null, match_type: null }, ...[3, 4, 5].map(index => pair(index, 'uic_match'))],
  ...changes
});
const oneSided = (source, count) => ({
  rows: Array.from({ length: count }, (_, index) => ({
    atlas: source === 'atlas' ? stop('fixed' + index, index + 1) : null,
    osm: source === 'osm' ? stop('fixed' + index, index + 1) : null, match_type: null
  })),
  matched_stop_count: 0, atlas_stop_count: source === 'atlas' ? count : 0, osm_stop_count: source === 'osm' ? count : 0,
  percentage: null, direction_status: 'unknown'
});
// A saved match: twelve shared stops in a row, then a stop only ATLAS serves.
const savedComparison = {
  rows: [...Array.from({ length: 12 }, (_, index) => pair(index + 1)), { atlas: stop('a13', 13), osm: null, match_type: null }],
  matched_stop_count: 12, atlas_stop_count: 13, osm_stop_count: 12, percentage: 92.3, direction_status: 'match'
};
const options = (items, page = 1, pages = 1, total = items.length) => ({ items, page, pages, total });
// Rendered by the server from itinerary_best_overlaps; the script must leave it alone.
const SERVER_BADGE = 'Highest overlap: 88.9%';
const response = data => ({ ok: true, json: async () => data });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const flush = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };
const node = (panel, hook) => document.getElementById(panel).querySelector('[data-comparison-' + hook + ']');
const badge = panel => document.getElementById(panel).querySelector('.route-card__overlap');
const rows = panel => [...node(panel, 'results').querySelectorAll('.comparison-row')];
const setOpen = (id, open = true) => {
  const panel = document.getElementById(id);
  panel.open = open;
  panel.dispatchEvent(new Event('toggle'));
};
const key = (target, name) => target.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true }));
const panelHtml = (id, { mode = 'explore', fixedSource = 'atlas', fixedId = '101', best = null, variant }) => `
  <details id="${id}" class="route-card__panel">
    <summary>Variant <span class="route-card__overlap">${SERVER_BADGE}</span></summary>
    <section class="variant-comparison" data-mode="${mode}" data-variant-data="${id}Data" data-source-label="ATLAS"
      ${mode === 'explore' ? `data-fixed-source="${fixedSource}" data-fixed-itinerary-id="${fixedId}"
        data-options-url="/api/routes/comparison/options" data-comparison-url="/api/routes/comparison"` : ''}
      ${best ? `data-best-id="${best.id}" data-best-label="${best.label}" data-best-percentage="${best.percentage}"
        data-best-matched-stops="${best.matched}"` : ''}>
      ${mode === 'explore' ? `<div data-comparison-picker>
        <button data-comparison-prev disabled>Previous</button>
        <button data-comparison-trigger aria-expanded="false">
          <span data-comparison-value></span><span data-comparison-value-meta></span><span data-comparison-value-score></span>
        </button>
        <button data-comparison-next disabled>Next</button>
        <div data-comparison-popover hidden>
          <input data-comparison-search type="search"><p data-comparison-position></p>
          <ul id="${id}Options" role="listbox" data-comparison-options></ul>
          <button data-comparison-more hidden>Show more</button>
        </div>
      </div>` : ''}
      <div data-comparison-status></div><div data-comparison-summary hidden></div>
      <p data-comparison-empty hidden></p><ol data-comparison-results></ol>
    </section>
    <script type="application/json" id="${id}Data">${JSON.stringify(variant)}</script>
  </details>`;

describe('Route variant comparisons', () => {
  let requests;
  let resolveRequest;
  let mounted;

  beforeAll(() => loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes-comparison.js')));

  beforeEach(() => {
    document.body.innerHTML = [
      panelHtml('savedPanel', { mode: 'saved', variant: { stop_comparison: savedComparison, osm_relation_id: '5551' } }),
      panelHtml('atlasPanel', { variant: { stop_comparison: oneSided('atlas', 3) },
        best: { id: '301', label: '10 · OSM best · Central → Lake · Direction 0', percentage: 80, matched: 4 } }),
      panelHtml('osmPanel', { fixedSource: 'osm', fixedId: '202', variant: { stop_comparison: oneSided('osm', 2) } })
    ].join('');
    requests = [];
    resolveRequest = url => {
      if (url.pathname.endsWith('/options')) return url.searchParams.get('source') === 'osm'
        ? options([osmBest, osmLower]) : options([atlasBest, atlasLower]);
      const atlasId = url.searchParams.get('atlas_itinerary_id');
      const osmId = url.searchParams.get('osm_itinerary_id');
      const selected = [osmBest, osmLower, osmLast, atlasBest, atlasLower]
        .find(item => item.id === (atlasId === '101' ? osmId : atlasId));
      return result(atlasId, osmId, { percentage: selected.percentage, osm: { ...selected, id: osmId } });
    };
    window.fetch = jest.fn((value, fetchOptions) => {
      const url = new URL(value);
      requests.push({ url, signal: fetchOptions.signal });
      return Promise.resolve(resolveRequest(url)).then(response);
    });
    mounted = window.RoutesComparison.init();
  });

  afterEach(() => {
    window.RoutesComparison.destroy();
    jest.useRealTimers();
  });

  test('renders a saved match from the page data on expansion, mirrored, with long matching runs folded', async () => {
    expect(mounted).toHaveLength(3);
    expect(window.RoutesComparison.init()).toEqual(mounted);
    expect(rows('savedPanel')).toHaveLength(0);
    setOpen('savedPanel');
    await flush();
    expect(requests).toHaveLength(0);
    const summary = node('savedPanel', 'summary');
    expect(summary.hidden).toBe(false);
    expect(summary.textContent).toContain('92.3%');
    expect(summary.textContent).toContain('12 of 13 stops match in order');
    expect(summary.textContent).toContain('1 only in ATLAS · 0 only in OSM');
    expect(summary.textContent).toContain('Saved match');
    expect(summary.textContent).toContain('Directions agree');
    expect(summary.querySelector('a').href).toBe('https://www.openstreetmap.org/relation/5551');

    const all = rows('savedPanel');
    expect(all).toHaveLength(13);
    const first = all[0];
    expect(first.classList).toContain('comparison-row--matched');
    expect(first.querySelector('.comparison-stop--atlas .comparison-stop__position').textContent).toBe('1');
    expect(first.querySelector('.comparison-stop--atlas .comparison-stop__position').title).toBe('Stop sequence 2');
    expect(first.querySelector('.comparison-stop--osm .comparison-stop__name').textContent).toBe('o1');
    expect(first.querySelector('.comparison-link--stop .visually-hidden').textContent).toBe('matched by stop');
    expect(all[12].classList).toContain('comparison-row--atlas-only');
    expect(all[12].querySelector('.comparison-stop--osm').textContent).toBe('Not in OSM');

    // Rows 3 to 10 fold; two matching stops stay visible at each end of the run.
    const fold = node('savedPanel', 'results').querySelector('.comparison-fold__button');
    expect(fold.textContent).toBe('Show 8 matching stops');
    expect(all.filter(row => row.hidden).map(row => row.querySelector('.comparison-stop__name').textContent))
      .toEqual(['a3', 'a4', 'a5', 'a6', 'a7', 'a8', 'a9', 'a10']);
    fold.click();
    expect(all.some(row => row.hidden)).toBe(false);
    expect(node('savedPanel', 'results').querySelector('.comparison-fold')).toBeNull();

    setOpen('savedPanel', false);
    setOpen('savedPanel');
    expect(rows('savedPanel')).toHaveLength(13);
  });

  test('shows an unmatched variant at once and compares the stored best while ranking candidates', async () => {
    await flush();
    expect(requests).toHaveLength(0);
    setOpen('atlasPanel');
    expect(rows('atlasPanel')).toHaveLength(3);
    expect(node('atlasPanel', 'results').classList).toContain('comparison-rows--single');
    expect(node('atlasPanel', 'value').textContent).toBe('10 · OSM best · Central → Lake · Direction 0');
    expect(node('atlasPanel', 'value-score').textContent).toBe('80%');
    const [comparison, ranking] = requests.map(request => request.url);
    expect(comparison.pathname).toBe('/api/routes/comparison');
    expect([comparison.searchParams.get('atlas_itinerary_id'), comparison.searchParams.get('osm_itinerary_id')]).toEqual(['101', '301']);
    expect(ranking.pathname).toBe('/api/routes/comparison/options');
    expect(Object.fromEntries(['source', 'fixed_itinerary_id', 'unmatched', 'shared_only', 'q']
      .map(name => [name, ranking.searchParams.get(name)]))).toEqual({
      source: 'osm', fixed_itinerary_id: '101', unmatched: '0', shared_only: '1', q: ''
    });

    await flush();
    expect(requests).toHaveLength(2);
    const summary = node('atlasPanel', 'summary').textContent;
    expect(summary).toContain('80%');
    expect(summary).toContain('4 of 5 stops match in order');
    expect(summary).toContain('OSM variant is the saved match of another ATLAS variant');
    expect(summary).not.toContain('Saved match');
    expect(node('atlasPanel', 'summary').querySelector('a').href).toBe('https://www.openstreetmap.org/relation/9301');
    expect(node('atlasPanel', 'results').classList).not.toContain('comparison-rows--single');
    expect(rows('atlasPanel')[1].classList).toContain('comparison-row--atlas-only');
    expect(rows('atlasPanel')[2].querySelector('.comparison-link__mark').textContent).toBe('UIC');
    expect(node('atlasPanel', 'value').textContent).toBe('Central → Lake');
    expect(node('atlasPanel', 'value-meta').textContent).toBe('OSM best · Direction 0 · 4 shared stops');
    expect(node('atlasPanel', 'prev').disabled).toBe(true);
    expect(node('atlasPanel', 'next').disabled).toBe(false);
    expect(badge('atlasPanel').textContent).toBe(SERVER_BADGE);
  });

  test('names saved counterparts and points to the one shown on the same route card', async () => {
    window.RoutesComparison.destroy();
    document.body.innerHTML = `<article class="route-card">
      <details id="pairPanel" class="route-card__panel" data-atlas-itinerary-id="150" data-osm-itinerary-id="301">
        <summary>Saved pair</summary>
      </details>
      ${panelHtml('atlasPanel', { variant: { stop_comparison: oneSided('atlas', 3) } })}
    </article>`;
    const onCard = { id: 150, route_id: '10', route_name: 'Line 10', display_name: 'Lake → Central',
      label: '10 · Line 10 · Lake → Central · Direction 1' };
    const elsewhere = { id: 160, route_id: '11', route_name: 'Line 11', display_name: 'Hill → Lake',
      label: '11 · Line 11 · Hill → Lake' };
    const taken = { ...osmBest, matched_with: [onCard, elsewhere] };
    resolveRequest = url => {
      if (url.pathname.endsWith('/options')) return options([taken, osmLower]);
      const osmId = url.searchParams.get('osm_itinerary_id');
      return result('101', osmId, { osm: osmId === '301' ? taken : osmLower });
    };
    window.RoutesComparison.init();
    setOpen('atlasPanel');
    await flush();

    const badge = node('atlasPanel', 'summary').querySelector('.comparison-badge--taken');
    expect(badge.textContent).toBe('Already matched to ATLAS Line 10 · Lake → Central, Line 11 · Hill → Lake');
    const [linked, other] = badge.querySelectorAll('.comparison-badge__target');
    expect(linked.tagName).toBe('BUTTON');
    expect(linked.title).toBe('10 · Line 10 · Lake → Central · Direction 1 · Show it on this route card');
    expect(other.tagName).toBe('STRONG');
    expect(other.title).toBe('11 · Line 11 · Hill → Lake');

    const pairPanel = document.getElementById('pairPanel');
    badge.dispatchEvent(new MouseEvent('mouseenter'));
    expect(pairPanel.classList).toContain('is-counterpart-highlighted');
    badge.dispatchEvent(new MouseEvent('mouseleave'));
    expect(pairPanel.classList).not.toContain('is-counterpart-highlighted');
    linked.click();
    expect(pairPanel.open).toBe(true);
    expect(pairPanel.classList).toContain('is-counterpart-flash');

    node('atlasPanel', 'trigger').click();
    expect(node('atlasPanel', 'options').querySelector('.comparison-option__flag').title)
      .toBe('Saved match of ATLAS Line 10 · Lake → Central, Line 11 · Hill → Lake');

    // A highlight does not outlive the badge that set it.
    node('atlasPanel', 'summary').querySelector('.comparison-badge--taken').dispatchEvent(new MouseEvent('mouseenter'));
    expect(pairPanel.classList).toContain('is-counterpart-highlighted');
    node('atlasPanel', 'next').click();
    await flush();
    expect(pairPanel.classList).not.toContain('is-counterpart-highlighted');
    expect(node('atlasPanel', 'summary').querySelector('.comparison-badge--taken')).toBeNull();
  });

  test('without a stored best, compares the top shared candidate of the other source', async () => {
    setOpen('osmPanel');
    await flush();
    expect(requests[0].url.searchParams.get('source')).toBe('atlas');
    expect(requests[0].url.searchParams.get('shared_only')).toBe('1');
    const comparison = requests[1].url.searchParams;
    expect([comparison.get('atlas_itinerary_id'), comparison.get('osm_itinerary_id')]).toEqual(['401', '202']);
    expect(node('osmPanel', 'summary').textContent).toContain('100%');
  });

  test('lists candidates by overlap in a popover and selects one with the keyboard', async () => {
    setOpen('atlasPanel');
    await flush();
    const trigger = node('atlasPanel', 'trigger');
    trigger.click();
    expect(node('atlasPanel', 'popover').hidden).toBe(false);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(node('atlasPanel', 'search'));
    expect(node('atlasPanel', 'position').textContent).toBe('2 OSM variants share stops with this one · highest overlap first');
    const choices = [...node('atlasPanel', 'options').querySelectorAll('[role="option"]')];
    expect(choices.map(option => option.querySelector('.comparison-option__percent').textContent)).toEqual(['80%', '60%']);
    expect(choices[0].getAttribute('aria-selected')).toBe('true');
    expect(choices[0].querySelector('.comparison-option__line').textContent).toBe('OSM best');
    expect(choices[0].querySelector('.comparison-option__flag').textContent).toBe('Already matched');
    expect(choices[0].querySelector('.comparison-option__fill').style.width).toBe('80%');
    expect(choices[1].querySelector('.comparison-option__meta').textContent).toBe('10 · Direction 0 · 3 shared stops');

    key(node('atlasPanel', 'search'), 'ArrowDown');
    expect(node('atlasPanel', 'search').getAttribute('aria-activedescendant')).toBe('atlasPanelOptions-302');
    key(node('atlasPanel', 'search'), 'Enter');
    expect(node('atlasPanel', 'popover').hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);
    expect(requests.at(-1).url.searchParams.get('osm_itinerary_id')).toBe('302');
    await flush();
    expect(node('atlasPanel', 'summary').textContent).toContain('60%');

    trigger.click();
    key(node('atlasPanel', 'search'), 'Escape');
    expect(node('atlasPanel', 'popover').hidden).toBe(true);
    trigger.click();
    node('atlasPanel', 'options').querySelector('[role="option"]').click();
    expect(requests.at(-1).url.searchParams.get('osm_itinerary_id')).toBe('301');
  });

  test('keeps open panels independent and their choices across collapse and reopen', async () => {
    setOpen('atlasPanel');
    setOpen('osmPanel');
    await flush();
    node('atlasPanel', 'next').click();
    await flush();
    expect(node('atlasPanel', 'summary').textContent).toContain('60%');
    expect(node('osmPanel', 'summary').textContent).toContain('100%');
    const count = requests.length;
    setOpen('atlasPanel', false);
    setOpen('atlasPanel');
    await flush();
    expect(requests).toHaveLength(count);
    expect(node('atlasPanel', 'summary').textContent).toContain('60%');
    expect(badge('atlasPanel').textContent).toBe(SERVER_BADGE);
  });

  test('steps through the ranking and appends its next page', async () => {
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/options')
      ? (url.searchParams.get('page') === '2' ? options([osmLast], 2, 2, 3) : options([osmBest, osmLower], 1, 2, 3))
      : original(url);
    setOpen('atlasPanel');
    await flush();
    node('atlasPanel', 'next').click();
    await flush();
    node('atlasPanel', 'next').click();
    await flush();
    expect(requests.filter(request => request.url.searchParams.get('page') === '2')).toHaveLength(1);
    expect(requests.at(-1).url.searchParams.get('osm_itinerary_id')).toBe('303');
    expect(node('atlasPanel', 'options').querySelectorAll('[role="option"]')).toHaveLength(3);
    expect(node('atlasPanel', 'next').disabled).toBe(true);
    expect(node('atlasPanel', 'more').hidden).toBe(true);
    node('atlasPanel', 'prev').click();
    expect(requests.at(-1).url.searchParams.get('osm_itinerary_id')).toBe('302');
  });

  test('loads more candidates from the popover', async () => {
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/options')
      ? (url.searchParams.get('page') === '2' ? options([osmLast], 2, 2, 3) : options([osmBest, osmLower], 1, 2, 3))
      : original(url);
    setOpen('atlasPanel');
    await flush();
    node('atlasPanel', 'trigger').click();
    expect(node('atlasPanel', 'more').hidden).toBe(false);
    node('atlasPanel', 'more').click();
    await flush();
    expect(node('atlasPanel', 'options').querySelectorAll('[role="option"]')).toHaveLength(3);
    expect(requests.at(-1).url.searchParams.get('page')).toBe('2');
    expect(node('atlasPanel', 'summary').textContent).toContain('80%');
  });

  test('a search reaches every route, debounces, and ignores obsolete responses', async () => {
    jest.useFakeTimers();
    setOpen('atlasPanel');
    await flush();
    const search = node('atlasPanel', 'search');
    const stale = deferred();
    const latest = deferred();
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/options')
      ? (url.searchParams.get('q') === 'old' ? stale.promise : latest.promise) : original(url);
    const count = requests.length;
    search.value = 'old';
    search.dispatchEvent(new Event('input'));
    jest.advanceTimersByTime(249);
    expect(requests).toHaveLength(count);
    jest.advanceTimersByTime(1);
    expect(requests.at(-1).url.searchParams.get('shared_only')).toBe('0');
    search.value = ' fresh ';
    search.dispatchEvent(new Event('input'));
    stale.reject(new Error('Obsolete failure'));
    await flush();
    expect(node('atlasPanel', 'position').textContent).toBe('Searching OSM routes…');
    jest.advanceTimersByTime(250);
    expect(requests.at(-1).url.searchParams.get('q')).toBe('fresh');
    latest.resolve(options([osmLast]));
    await flush();
    expect(node('atlasPanel', 'position').textContent).toBe('1 route matches “fresh” · highest overlap first');
    expect(node('atlasPanel', 'options').textContent).toContain('OSM last');
    // A search changes the list, not the comparison.
    expect(node('atlasPanel', 'summary').textContent).toContain('80%');
    resolveRequest = original;
    search.value = '';
    search.dispatchEvent(new Event('input'));
    jest.advanceTimersByTime(250);
    expect(requests.at(-1).url.searchParams.get('shared_only')).toBe('1');
  });

  test('keeps the variant stops and suggests a search when no candidate shares a stop', async () => {
    resolveRequest = () => options([]);
    setOpen('osmPanel');
    await flush();
    expect(requests).toHaveLength(1);
    expect(node('osmPanel', 'empty').hidden).toBe(false);
    expect(node('osmPanel', 'empty').textContent).toContain('No ATLAS variant shares a stop with this one');
    expect(node('osmPanel', 'value').textContent).toBe('Choose a variant to compare');
    expect(rows('osmPanel')).toHaveLength(2);
    expect(node('osmPanel', 'next').disabled).toBe(true);
    node('osmPanel', 'trigger').click();
    expect(node('osmPanel', 'position').textContent).toContain('Search to compare with any route');
  });

  test('dims the shown comparison while the next loads and ignores obsolete responses', async () => {
    setOpen('atlasPanel');
    await flush();
    const oldSuccess = deferred(), oldFailure = deferred(), latest = deferred();
    let count = 0;
    resolveRequest = () => [oldSuccess.promise, oldFailure.promise, latest.promise][count++];
    const section = document.querySelector('#atlasPanel .variant-comparison');
    node('atlasPanel', 'next').click();
    expect(section.getAttribute('aria-busy')).toBe('true');
    expect(node('atlasPanel', 'summary').textContent).toContain('80%');
    expect(node('atlasPanel', 'status').textContent).toBe('Comparing stops…');
    node('atlasPanel', 'prev').click();
    node('atlasPanel', 'next').click();
    oldSuccess.resolve(result('101', '302', { percentage: 99 }));
    oldFailure.reject(new Error('Old request failure'));
    await flush();
    expect(node('atlasPanel', 'summary').textContent).not.toContain('99%');
    latest.resolve(result('101', '302', { percentage: 60 }));
    await flush();
    expect(section.getAttribute('aria-busy')).toBe('false');
    expect(node('atlasPanel', 'summary').textContent).toContain('60%');
    expect(node('atlasPanel', 'status').textContent).toBe('');
  });

  test('recovers from ranking and comparison failures and falls back to the variant stops', async () => {
    window.RoutesComparison.destroy();
    window.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 503 }));
    window.RoutesComparison.init();
    setOpen('osmPanel');
    await flush();
    expect(node('osmPanel', 'value').textContent).toBe('Could not load ATLAS variants');
    expect(node('osmPanel', 'position').textContent).toContain('Could not load ATLAS variants');
    window.fetch = jest.fn(value => Promise.resolve(new URL(value).pathname.endsWith('/options')
      ? response(options([atlasBest])) : { ok: false, status: 404 }));
    node('osmPanel', 'position').querySelector('button').click();
    await flush();
    expect(node('osmPanel', 'status').textContent).toContain('Could not compare these variants');
    expect(node('osmPanel', 'summary').hidden).toBe(true);
    expect(node('osmPanel', 'results').classList).toContain('comparison-rows--single');
    window.fetch = jest.fn(() => Promise.resolve(response(result('401', '202'))));
    node('osmPanel', 'status').querySelector('button').click();
    await flush();
    expect(node('osmPanel', 'summary').textContent).toContain('80%');
    expect(node('osmPanel', 'results').classList).not.toContain('comparison-rows--single');
  });

  test('restores the variant on its map after a failed comparison', async () => {
    const changes = [];
    const listener = event => changes.push(event.detail && event.detail.percentage);
    document.addEventListener('routecomparisonchange', listener);
    setOpen('atlasPanel');
    await flush();
    resolveRequest = () => Promise.reject(new Error('offline'));
    node('atlasPanel', 'next').click();
    await flush();
    expect(changes).toEqual([80, null]);
    document.removeEventListener('routecomparisonchange', listener);
  });

  test('renders server strings safely and flags direction conflicts', async () => {
    const unsafe = '<img src=x onerror=alert(1)>';
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/comparison')
      ? result('101', '301', { direction_status: 'conflict', rows: [{ atlas: stop(unsafe, 1, unsafe), osm: null, match_type: null }] })
      : original(url);
    setOpen('atlasPanel');
    await flush();
    expect(node('atlasPanel', 'results').textContent).toContain(unsafe);
    expect(document.querySelector('img')).toBeNull();
    expect(node('atlasPanel', 'summary').textContent).toContain('Direction conflict');
    resolveRequest = () => result('101', '302', { percentage: null, direction_status: 'unknown', rows: [] });
    node('atlasPanel', 'next').click();
    await flush();
    expect(node('atlasPanel', 'summary').textContent).toContain('—');
    expect(node('atlasPanel', 'summary').textContent).toContain('Direction unknown');
    expect(node('atlasPanel', 'empty').hidden).toBe(false);
  });

  test('row hover and click send the stop positions to the variant map', async () => {
    const events = [];
    const record = event => events.push([event.type, event.target.closest('details').id, event.detail]);
    document.addEventListener('routecomparisonhover', record);
    document.addEventListener('routecomparisonfocus', record);
    setOpen('savedPanel');
    const [first, second] = rows('savedPanel');
    first.querySelector('.comparison-stop__name').dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    first.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    second.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    node('savedPanel', 'results').dispatchEvent(new MouseEvent('mouseleave'));
    second.click();
    expect(events).toEqual([
      ['routecomparisonhover', 'savedPanel', [[47, 8], [47, 8]]],
      ['routecomparisonhover', 'savedPanel', [[47, 8], [47, 8]]],
      ['routecomparisonhover', 'savedPanel', null],
      ['routecomparisonfocus', 'savedPanel', [[47, 8], [47, 8]]]
    ]);
    document.removeEventListener('routecomparisonhover', record);
    document.removeEventListener('routecomparisonfocus', record);
  });

  test('defers the comparison if a panel collapses before its candidates arrive', async () => {
    const pending = deferred();
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/options') ? pending.promise : original(url);
    setOpen('osmPanel');
    setOpen('osmPanel', false);
    pending.resolve(options([atlasBest]));
    await flush();
    expect(requests.some(request => request.url.pathname.endsWith('/comparison'))).toBe(false);
    setOpen('osmPanel');
    await flush();
    expect(node('osmPanel', 'summary').textContent).toContain('100%');
  });

  test('preserves bfcache controls and cleans pending searches on final teardown', async () => {
    jest.useFakeTimers();
    setOpen('atlasPanel');
    await flush();
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
    node('atlasPanel', 'next').click();
    expect(requests.at(-1).url.searchParams.get('osm_itinerary_id')).toBe('302');
    node('atlasPanel', 'search').dispatchEvent(new Event('input'));
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }));
    expect(jest.getTimerCount()).toBe(0);
    const count = requests.length;
    node('atlasPanel', 'prev').click();
    setOpen('osmPanel');
    expect(requests).toHaveLength(count);
  });
});
