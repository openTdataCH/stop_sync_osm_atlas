const path = require('path');
const loadBrowserScript = require('./load-browser-script');

const candidate = (id, score, name = 'Line 10', isMatched = false) => ({
  id, route_id: '10', route_name: name, display_name: 'Central → Lake', direction_id: 0,
  percentage: score, stop_ratio: score / 100, matched_stop_count: score / 20, is_matched: isMatched
});
const osmBest = candidate('301', 80, 'OSM best', true);
const osmLower = candidate('302', 60, 'OSM alternative');
const osmLast = candidate('303', 0, 'OSM last');
const atlasBest = candidate('401', 100, 'ATLAS best');
const atlasLower = candidate('402', 40, 'ATLAS alternative');
const stop = (id, label = id) => ({ id, stop_sequence: 1, stop_label: label, stop_ids: [id], uic_ref: null });
const result = (atlasId = '101', osmId = '301', changes = {}) => ({
  atlas: { ...candidate(atlasId, 80), id: atlasId }, osm: { ...candidate(osmId, 80), id: osmId },
  matched_stop_count: 4, atlas_stop_count: 5, osm_stop_count: 4,
  stop_ratio: 0.8, percentage: 80, direction_status: 'match', is_saved_match: false,
  rows: [
    { atlas: stop('a-stop'), osm: stop('o-stop'), match_type: 'resolved_sloid_match' },
    { atlas: stop('a-gap'), osm: null, match_type: null },
    ...[1, 2, 3].map(id => ({ atlas: stop('a-' + id), osm: stop('o-' + id), match_type: 'uic_match' }))
  ], ...changes
});
const options = (items, best = items[0] || null, page = 1, pages = 1, total = items.length) => ({ items, best, page, pages, total });
const response = data => ({ ok: true, json: async () => data });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const flush = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };
const node = (panel, hook) => document.getElementById(panel).querySelector('[data-comparison-' + hook + ']');
const badge = panel => document.getElementById(panel).querySelector('[data-best-overlap]');
const setOpen = (id, open = true) => {
  const panel = document.getElementById(id);
  panel.open = open;
  panel.dispatchEvent(new Event('toggle'));
};
const select = (panel, value) => {
  node(panel, 'select').value = value;
  node(panel, 'select').dispatchEvent(new Event('change'));
};
const panelHtml = (id, fixedSource, fixedId) => `
  <details id="${id}" class="route-card__panel">
    <summary>Variant <span data-best-overlap>Finding overlap…</span></summary>
    <section class="variant-comparison" data-fixed-source="${fixedSource}" data-fixed-itinerary-id="${fixedId}"
      data-options-url="/api/routes/comparison/options" data-best-url="/api/routes/comparison/best"
      data-comparison-url="/api/routes/comparison" data-source-label="ATLAS">
      <input data-comparison-search type="search"><select data-comparison-select></select>
      <button data-comparison-prev disabled>Previous</button><button data-comparison-next disabled>Next</button>
      <span data-comparison-position></span><span data-comparison-candidate-name></span>
      <div data-comparison-status></div><div data-comparison-summary hidden></div>
      <div data-comparison-results></div><div data-comparison-empty>Choose a candidate</div>
      <div data-comparison-fallback>Original fixed stop list</div>
    </section>
  </details>`;

describe('Independent inline route comparisons', () => {
  let requests;
  let resolveRequest;
  let mounted;

  beforeAll(() => loadBrowserScript(path.join(__dirname, '../../static/js/pages/routes-comparison.js')));

  beforeEach(() => {
    document.body.innerHTML = panelHtml('atlasPanel', 'atlas', '101') + panelHtml('osmPanel', 'osm', '202');
    requests = [];
    resolveRequest = url => {
      if (url.pathname.endsWith('/best')) return { items: { '101': osmBest, '202': atlasBest } };
      if (url.pathname.endsWith('/options')) return url.searchParams.get('source') === 'osm'
        ? options([osmBest, osmLower]) : options([atlasBest, atlasLower]);
      const atlasId = url.searchParams.get('atlas_itinerary_id');
      const osmId = url.searchParams.get('osm_itinerary_id');
      const selected = [osmBest, osmLower, osmLast, atlasBest, atlasLower].find(item => item.id === (atlasId === '101' ? osmId : atlasId));
      return result(atlasId, osmId, { percentage: selected.percentage });
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

  test('batches collapsed badges while loading no candidates or comparisons until expansion', async () => {
    await flush();
    expect(mounted).toHaveLength(2);
    expect(requests).toHaveLength(1);
    expect(requests[0].url.pathname).toBe('/api/routes/comparison/best');
    expect(requests[0].url.searchParams.getAll('itinerary_id')).toEqual(['101', '202']);
    expect(badge('atlasPanel').textContent).toBe('Highest overlap: 80%');
    expect(badge('osmPanel').textContent).toBe('Highest overlap: 100%');
    expect(window.RoutesComparison.init()).toEqual(mounted);
    expect(requests).toHaveLength(1);
    setOpen('atlasPanel');
    await flush();
    expect(requests[1].url.searchParams.get('fixed_itinerary_id')).toBe('101');
    expect(requests[1].url.searchParams.get('source')).toBe('osm');
    expect(requests[1].url.searchParams.get('unmatched')).toBe('0');
    expect(node('atlasPanel', 'select').value).toBe('301');
    expect(node('atlasPanel', 'select').selectedOptions[0].textContent).toContain('80% overlap · 10 · OSM best');
    expect(node('atlasPanel', 'select').selectedOptions[0].textContent).toContain('Already matched');
    expect(node('osmPanel', 'summary').hidden).toBe(true);
  });

  test('keeps concurrently open panels independent and preserves choices across collapse and reopen', async () => {
    setOpen('atlasPanel');
    setOpen('osmPanel');
    await flush();
    expect(node('atlasPanel', 'select').value).toBe('301');
    expect(node('osmPanel', 'select').value).toBe('401');
    node('atlasPanel', 'next').click();
    await flush();
    expect(node('atlasPanel', 'select').value).toBe('302');
    expect(node('atlasPanel', 'summary').textContent).toContain('60%');
    expect(node('osmPanel', 'select').value).toBe('401');
    expect(node('osmPanel', 'summary').textContent).toContain('100%');
    expect(badge('atlasPanel').textContent).toBe('Highest overlap: 80%');
    const count = requests.length;
    setOpen('atlasPanel', false);
    setOpen('atlasPanel');
    await flush();
    expect(requests).toHaveLength(count);
    expect(node('atlasPanel', 'select').value).toBe('302');
    const comparisons = requests.filter(request => request.url.pathname.endsWith('/comparison'));
    expect(comparisons.map(request => [request.url.searchParams.get('atlas_itinerary_id'), request.url.searchParams.get('osm_itinerary_id')]))
      .toEqual([['101', '301'], ['401', '202'], ['101', '302']]);
  });

  test('renders linked stop alignments, score details and map events only for the affected panel', async () => {
    const changes = [];
    const listenerController = new AbortController();
    document.addEventListener('routecomparisonchange', event => changes.push({ target: event.target, detail: event.detail }), { signal: listenerController.signal });
    setOpen('atlasPanel');
    await flush();
    expect(node('atlasPanel', 'summary').hidden).toBe(false);
    expect(node('atlasPanel', 'summary').textContent).toContain('4 of 5 stops match in sequence');
    expect(node('atlasPanel', 'summary').textContent).toContain('ATLAS: 1 only · OSM: 0 only');
    expect(node('atlasPanel', 'results').children).toHaveLength(5);
    expect(node('atlasPanel', 'results').querySelectorAll('.comparison-link--matched')).toHaveLength(4);
    expect(node('atlasPanel', 'results').querySelectorAll('.comparison-link')[1].textContent).toBe('');
    expect(node('atlasPanel', 'results').querySelectorAll('.comparison-link__symbol')[1].textContent).toBe('UIC ↔');
    expect(node('atlasPanel', 'fallback').hidden).toBe(true);
    expect(changes.map(change => change.detail === null ? null : change.detail.percentage)).toEqual([null, 80]);
    expect(changes.every(change => change.target === document.querySelector('#atlasPanel .variant-comparison'))).toBe(true);
    listenerController.abort();
  });

  test('steps through ranked candidates across pages without changing the fixed route', async () => {
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/options')
      ? (url.searchParams.get('page') === '2' ? options([osmLast], osmBest, 2, 2, 3) : options([osmBest, osmLower], osmBest, 1, 2, 3))
      : original(url);
    setOpen('atlasPanel');
    await flush();
    node('atlasPanel', 'next').click();
    await flush();
    node('atlasPanel', 'next').click();
    await flush();
    expect(node('atlasPanel', 'select').value).toBe('303');
    expect(node('atlasPanel', 'position').textContent).toContain('page 2 of 2');
    expect(node('atlasPanel', 'next').disabled).toBe(true);
    expect(requests.at(-1).url.searchParams.get('atlas_itinerary_id')).toBe('101');
    expect(badge('atlasPanel').textContent).toBe('Highest overlap: 80%');
    node('atlasPanel', 'prev').click();
    await flush();
    expect(node('atlasPanel', 'select').value).toBe('302');
    expect(node('atlasPanel', 'position').textContent).toContain('page 1 of 2');
  });

  test('debounces each search independently and keeps comparisons selected outside search results', async () => {
    jest.useFakeTimers();
    setOpen('atlasPanel');
    setOpen('osmPanel');
    await flush();
    const count = requests.length;
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/options') && url.searchParams.get('q')
      ? options([osmLast], osmBest) : original(url);
    node('atlasPanel', 'search').value = ' Last ';
    node('atlasPanel', 'search').dispatchEvent(new Event('input'));
    jest.advanceTimersByTime(249);
    expect(requests).toHaveLength(count);
    jest.advanceTimersByTime(1);
    await flush();
    expect(requests.at(-1).url.searchParams.get('q')).toBe('Last');
    expect(node('atlasPanel', 'select').value).toBe('301');
    expect(Array.from(node('atlasPanel', 'select').options).map(option => option.value)).toEqual(['', '301', '303']);
    expect(node('atlasPanel', 'summary').textContent).toContain('80%');
    expect(node('osmPanel', 'select').value).toBe('401');
    expect(badge('atlasPanel').textContent).toBe('Highest overlap: 80%');
    node('atlasPanel', 'search').value = '';
    node('atlasPanel', 'search').dispatchEvent(new Event('input'));
    jest.advanceTimersByTime(250);
    await flush();
    expect(Array.from(node('atlasPanel', 'select').options).map(option => option.value)).toEqual(['', '301', '302']);
  });

  test('ignores obsolete search successes and failures without affecting another open comparison', async () => {
    jest.useFakeTimers();
    setOpen('atlasPanel');
    setOpen('osmPanel');
    await flush();
    const stale = deferred();
    const latest = deferred();
    resolveRequest = url => url.searchParams.get('q') === 'old' ? stale.promise : latest.promise;
    node('atlasPanel', 'search').value = 'old';
    node('atlasPanel', 'search').dispatchEvent(new Event('input'));
    jest.advanceTimersByTime(250);
    node('atlasPanel', 'search').value = 'fresh';
    node('atlasPanel', 'search').dispatchEvent(new Event('input'));
    stale.reject(new Error('Obsolete failure'));
    await flush();
    expect(node('atlasPanel', 'position').textContent).toContain('Finding routes');
    jest.advanceTimersByTime(250);
    latest.resolve(options([osmLast], osmBest));
    await flush();
    expect(node('atlasPanel', 'select').textContent).toContain('OSM last');
    expect(node('osmPanel', 'summary').textContent).toContain('100%');
  });

  test('clears old rows on candidate changes and ignores obsolete comparison responses and failures', async () => {
    setOpen('atlasPanel');
    await flush();
    const oldSuccess = deferred(), oldFailure = deferred(), latest = deferred();
    let count = 0;
    resolveRequest = () => [oldSuccess.promise, oldFailure.promise, latest.promise][count++];
    select('atlasPanel', '302');
    expect(node('atlasPanel', 'results').children).toHaveLength(0);
    expect(node('atlasPanel', 'summary').hidden).toBe(true);
    expect(node('atlasPanel', 'fallback').hidden).toBe(false);
    select('atlasPanel', '301');
    select('atlasPanel', '302');
    oldSuccess.resolve(result('101', '302', { percentage: 99 }));
    oldFailure.reject(new Error('Old request failure'));
    await flush();
    expect(node('atlasPanel', 'status').textContent).toBe('Comparing route stops…');
    latest.resolve(result('101', '302', { percentage: 60 }));
    await flush();
    expect(node('atlasPanel', 'summary').textContent).toContain('60%');
    expect(node('atlasPanel', 'summary').textContent).not.toContain('99%');
  });

  test('distinguishes zero overlap, unavailable sequences and no candidates in collapsed badges', async () => {
    window.RoutesComparison.destroy();
    document.body.innerHTML += panelHtml('emptyPanel', 'atlas', '103');
    resolveRequest = url => url.pathname.endsWith('/best')
      ? { items: { '101': candidate('301', 0), '202': candidate('401', null), '103': null } }
      : options([], null);
    window.RoutesComparison.init();
    await flush();
    expect(badge('atlasPanel').textContent).toBe('Highest overlap: 0%');
    expect(badge('osmPanel').textContent).toBe('Highest overlap: —');
    expect(badge('emptyPanel').textContent).toBe('No candidate routes');
    const count = requests.length;
    setOpen('emptyPanel');
    await flush();
    expect(requests).toHaveLength(count + 1);
    expect(node('emptyPanel', 'empty').textContent).toContain('No candidate routes');
    expect(node('emptyPanel', 'fallback').hidden).toBe(false);
    expect(node('emptyPanel', 'next').disabled).toBe(true);
  });

  test('recovers from badge, options and comparison failures while retaining the fixed stop list', async () => {
    window.RoutesComparison.destroy();
    window.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 503 }));
    window.RoutesComparison.init();
    await flush();
    expect(badge('atlasPanel').textContent).toBe('Overlap unavailable');
    setOpen('atlasPanel');
    await flush();
    expect(node('atlasPanel', 'position').textContent).toContain('Could not load OSM routes');
    window.fetch = jest.fn(value => Promise.resolve(new URL(value).pathname.endsWith('/options')
      ? response(options([osmBest])) : { ok: false, status: 404 }));
    node('atlasPanel', 'position').querySelector('button').click();
    await flush();
    expect(badge('atlasPanel').textContent).toBe('Highest overlap: 80%');
    expect(node('atlasPanel', 'status').textContent).toContain('Could not compare');
    expect(node('atlasPanel', 'fallback').hidden).toBe(false);
    window.fetch = jest.fn(() => Promise.resolve(response(result())));
    node('atlasPanel', 'status').querySelector('button').click();
    await flush();
    expect(node('atlasPanel', 'fallback').hidden).toBe(true);
    expect(node('atlasPanel', 'summary').textContent).toContain('80%');
  });

  test('renders server strings safely and supports empty stops and direction warnings', async () => {
    const unsafe = '<img src=x onerror=alert(1)>';
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/comparison')
      ? result('101', '301', { direction_status: 'conflict', rows: [{ atlas: stop(unsafe, unsafe), osm: null, match_type: null }] })
      : original(url);
    setOpen('atlasPanel');
    await flush();
    expect(node('atlasPanel', 'results').textContent).toContain(unsafe);
    expect(document.querySelector('img')).toBeNull();
    expect(node('atlasPanel', 'summary').textContent).toContain('Direction conflict');
    resolveRequest = () => result('101', '302', { percentage: null, direction_status: 'unknown', rows: [] });
    select('atlasPanel', '302');
    await flush();
    expect(node('atlasPanel', 'summary').textContent).toContain('—');
    expect(node('atlasPanel', 'summary').textContent).toContain('Direction unknown');
    expect(node('atlasPanel', 'empty').hidden).toBe(false);
  });

  test('clearing a candidate restores the original stops without another API comparison', async () => {
    setOpen('atlasPanel');
    await flush();
    const count = requests.length;
    select('atlasPanel', '');
    expect(requests).toHaveLength(count);
    expect(node('atlasPanel', 'fallback').hidden).toBe(false);
    expect(node('atlasPanel', 'summary').hidden).toBe(true);
    expect(node('atlasPanel', 'empty').textContent).toContain('Choose a route from OSM');
    expect(badge('atlasPanel').textContent).toBe('Highest overlap: 80%');
  });

  test('defers comparison if a panel collapses before its candidates arrive', async () => {
    const pending = deferred();
    const original = resolveRequest;
    resolveRequest = url => url.pathname.endsWith('/options') ? pending.promise : original(url);
    setOpen('atlasPanel');
    setOpen('atlasPanel', false);
    pending.resolve(options([osmBest]));
    await flush();
    expect(requests.some(request => request.url.pathname.endsWith('/comparison'))).toBe(false);
    setOpen('atlasPanel');
    await flush();
    expect(node('atlasPanel', 'summary').textContent).toContain('80%');
  });

  test('preserves bfcache controls and cleans pending searches on final teardown', async () => {
    jest.useFakeTimers();
    setOpen('atlasPanel');
    await flush();
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
    node('atlasPanel', 'next').click();
    await flush();
    expect(node('atlasPanel', 'select').value).toBe('302');
    node('atlasPanel', 'search').dispatchEvent(new Event('input'));
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false }));
    expect(jest.getTimerCount()).toBe(0);
    const count = requests.length;
    node('atlasPanel', 'prev').click();
    setOpen('osmPanel');
    expect(requests).toHaveLength(count);
  });
});
