const loadBrowserScript = require('./load-browser-script');
const path = require('path');

function codeMap() {
  return {
    schema_version: 1,
    modules: [
      { id: 'app.api', repository: 'app', title: 'API', criticality: 'high', responsibility: 'Serve data.', owner: 'Team', reviewed: '2026-10-01',
        invariants: ['Validate input.'], entrypoints: [{ entry: 'backend.api:serve', symbol: 'app:backend/api.py:serve@3' }], dependencies: [], tests: [], docs: {} },
      { id: 'app.import', repository: 'app', title: 'Import', criticality: 'critical', responsibility: 'Publish data.', owner: 'Team', reviewed: '2026-10-01',
        invariants: [], entrypoints: [], dependencies: ['app.api', 'app.ui'], tests: [], docs: {} },
      { id: 'app.ui', repository: 'app', title: 'UI', criticality: 'medium', responsibility: 'Show data.', owner: 'Team', reviewed: '2026-10-01',
        invariants: [], entrypoints: [], dependencies: [], tests: [], docs: {} },
      { id: 'engine.core', repository: 'engine', title: 'Core', criticality: 'critical', responsibility: 'Match.', owner: 'Team', reviewed: '2026-10-01',
        invariants: [], entrypoints: [], dependencies: [], tests: [], docs: {} }
    ],
    contracts: [{ id: 'bundle', title: 'Bundle', producers: ['engine.core'], consumers: ['app.import'] }],
    files: [
      { id: 'app:backend/api.py', module: 'app.api', lines: 400, symbols: 3 },
      { id: 'app:backend/api_helpers.py', module: 'app.api', lines: 100, symbols: 2 },
      { id: 'app:backend/importer.py', module: 'app.import', lines: 900, symbols: 5 },
      { id: 'app:static/js/ui.js', module: 'app.ui', lines: 50, symbols: 1 },
      { id: 'engine:src/core.py', module: 'engine.core', lines: 1200, symbols: 9 }
    ],
    links: [
      { source: 'app:backend/importer.py', target: 'app:backend/api.py', kind: 'imports', count: 2 },
      { source: 'app:backend/importer.py', target: 'app:backend/api.py', kind: 'calls', count: 3 },
      { source: 'app:backend/api.py', target: 'app:backend/importer.py', kind: 'uses', count: 1 },
      { source: 'app:backend/api.py', target: 'app:backend/api_helpers.py', kind: 'imports', count: 1 },
      { source: 'app:static/js/ui.js', target: 'app:backend/api.py', kind: 'requests', count: 2 },
      { source: 'app:backend/importer.py', target: 'app:static/js/ui.js', kind: 'links', count: 4 }
    ],
    routes: [
      { pattern: '/api/serve', methods: ['GET'], endpoint: 'api.serve', symbol: 'app:backend/api.py:serve@3', file: 'app:backend/api.py', line: 3,
        requested_by: ['app:static/js/ui.js'], linked_by: [] },
      { pattern: '/api/old', methods: ['POST'], endpoint: 'api.old', symbol: 'app:backend/api.py:old@20', file: 'app:backend/api.py', line: 20,
        requested_by: [], linked_by: [] }
    ],
    blind_spots: {
      unmatched: [{ file: 'app:static/js/ui.js', line: 7, kind: 'url', reference: '/api/missing' }],
      dynamic: [{ file: 'app:static/js/ui.js', line: 9, kind: 'request', expression: 'config.url' }],
      shared_names: [{ name: 'helper', symbols: ['app:static/js/ui.js:helper@1', 'app:static/js/other.js:helper@4'] }]
    },
    limitations: ['Static reading only.'],
    symbols: [
      { id: 'app:backend/api.py:serve@3', name: 'serve', file: 'app:backend/api.py', line: 3 },
      { id: 'app:backend/api.py:helper@10', name: 'helper', file: 'app:backend/api.py', line: 10 },
      { id: 'app:backend/api_helpers.py:fmt@2', name: 'fmt', file: 'app:backend/api_helpers.py', line: 2 },
      { id: 'app:backend/importer.py:run@5', name: 'run', file: 'app:backend/importer.py', line: 5 }
    ],
    symbol_links: [
      { source: 'app:backend/importer.py:run@5', target: 'app:backend/api.py:serve@3', kind: 'calls', count: 2 },
      { source: 'app:backend/api.py:serve@3', target: 'app:backend/api.py:helper@10', kind: 'calls', count: 1 },
      { source: 'app:backend/api.py:serve@3', target: 'app:backend/api_helpers.py:fmt@2', kind: 'calls', count: 1 },
      { source: 'app:static/js/ui.js', target: 'app:backend/api.py:serve@3', kind: 'requests', count: 2 },
      { source: 'app:backend/importer.py', target: 'app:backend/api.py:helper@10', kind: 'links', count: 1 }
    ],
    interface: {
      'app.api': [{ id: 'app:backend/api.py:serve@3', name: 'serve', file: 'app:backend/api.py', line: 3, used_by: ['app.import'] }],
      'app.import': [{ id: 'app:backend/importer.py:_private@9', name: '_private', file: 'app:backend/importer.py', line: 9, used_by: ['app.api'] }],
      'app.ui': [],
      'engine.core': []
    }
  };
}

function report() {
  return {
    completeness: 'partial', generated_at: '2026-11-01T10:00:00+00:00', revision: { app: 'a'.repeat(40), engine: 'b'.repeat(40) },
    checks: [{ name: 'app-python-tests', status: 'pass' }, { name: 'engine-tests', status: 'fail' }],
    modules: {
      'app.api': { criticality: 'high', tests: { status: 'pass', count: 12, skipped: 0, missing_files: [] }, coverage: { status: 'measured', branches: 87.5, lines: 91 },
        mutation: { status: 'not_measured' }, duplication: { status: 'attention', count: 3, new: 1 }, dead_code: { status: 'not_applicable' },
        docs: { status: 'pass', satisfied: 4, required: 4 }, architecture: { status: 'pass', violations: [] } },
      'app.import': { criticality: 'critical', tests: { status: 'fail', count: 1 }, coverage: { status: 'stale', branches: 12 } }
    }
  };
}

/** ``count`` modules of ``size`` functions in four files each, called in a chain inside a module and now and then across. */
function largeCodeMap(count, size) {
  const map = { modules: [], files: [], symbols: [], symbol_links: [], links: [] };
  for (let m = 0; m < count; m++) {
    const moduleId = 'app.m' + m;
    map.modules.push({ id: moduleId, repository: 'app', dependencies: m ? ['app.m0'] : [] });
    for (let f = 0; f < 4; f++) map.files.push({ id: 'app:m' + m + '/f' + f + '.py', module: moduleId });
    for (let k = 0; k < size; k++) {
      const file = 'app:m' + m + '/f' + (k % 4) + '.py';
      map.symbols.push({ id: file + ':s' + k + '@' + k, name: 'm' + m + '_s' + k, file, line: k });
      if (k) map.symbol_links.push({ source: file + ':s' + k + '@' + k, target: 'app:m' + m + '/f' + ((k - 1) % 4) + '.py:s' + (k - 1) + '@' + (k - 1), kind: 'calls', count: 1 });
    }
    if (m) map.symbol_links.push({ source: 'app:m' + m + '/f0.py:s0@0', target: 'app:m0/f1.py:s1@1', kind: 'calls', count: 1 });
  }
  return map;
}

describe('QualityDashboard', () => {
  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/quality/dashboard.js'));
  });

  test('module links separate declared, undeclared and code-free dependencies', () => {
    const links = window.QualityDashboard.aggregateModuleLinks(codeMap());
    const byKey = Object.fromEntries(links.map((link) => [link.source + '>' + link.target, link]));
    expect(byKey['app.import>app.api']).toMatchObject({ count: 5, declared: true, kinds: { imports: 2, calls: 3 } });
    expect(byKey['app.api>app.import']).toMatchObject({ count: 1, declared: false });
    expect(byKey['app.import>app.ui']).toMatchObject({ count: 0, declared: true });
    expect(links.some((link) => link.source === link.target)).toBe(false);
  });

  test('HTTP requests draw arrows, links to pages do not', () => {
    const links = window.QualityDashboard.aggregateModuleLinks(codeMap());
    const byKey = Object.fromEntries(links.map((link) => [link.source + '>' + link.target, link]));
    expect(byKey['app.ui>app.api']).toMatchObject({ count: 2, declared: false, kinds: { requests: 2 } });
    expect(byKey['app.import>app.ui']).toMatchObject({ count: 0, declared: true });
    const files = window.QualityDashboard.fileGraph(codeMap(), 'app.ui');
    expect(files.links.map((link) => link.source + '>' + link.target)).toEqual(['app:static/js/ui.js>app:backend/api.py']);
  });

  test('a file\'s function graph puts its functions in line order between their users and what they use', () => {
    const graph = window.QualityDashboard.functionGraph(codeMap(), 'app:backend/api.py');
    expect(graph.inside).toEqual(['app:backend/api.py:serve@3', 'app:backend/api.py:helper@10']);
    // A file-level user, as a script's request, has no function of its own; a page link draws nothing.
    expect(graph.users).toEqual({ 'app:backend/importer.py': ['app:backend/importer.py:run@5'], 'app:static/js/ui.js': [] });
    expect(graph.used).toEqual({ 'app:backend/api_helpers.py': ['app:backend/api_helpers.py:fmt@2'] });
    expect(Array.from(graph.entries)).toEqual(['app:backend/api.py:serve@3']);
    const byKey = Object.fromEntries(graph.links.map((link) => [link.source + '>' + link.target, link]));
    expect(byKey['app:backend/importer.py:run@5>app:backend/api.py:serve@3']).toMatchObject({ crossing: true, declared: true, count: 2 });
    expect(byKey['app:static/js/ui.js>app:backend/api.py:serve@3']).toMatchObject({ crossing: true, declared: false, kinds: { requests: 2 } });
    expect(byKey['app:backend/api.py:serve@3>app:backend/api.py:helper@10']).toMatchObject({ crossing: false });
    expect(byKey['app:backend/importer.py>app:backend/api.py:helper@10']).toBeUndefined();
  });

  test('blind spots list unmatched references, unreached routes, runtime URLs and shared names', () => {
    const spots = window.QualityDashboard.blindSpots(codeMap());
    expect(spots.unmatched.map((row) => row.reference)).toEqual(['/api/missing']);
    expect(spots.unreached.map((route) => route.pattern)).toEqual(['/api/old']);
    expect(spots.dynamic.map((row) => row.expression)).toEqual(['config.url']);
    expect(spots.sharedNames.map((row) => row.name)).toEqual(['helper']);
    expect(window.QualityDashboard.blindSpots({ files: [], links: [] })).toEqual({ unmatched: [], unreached: [], dynamic: [], sharedNames: [] });
  });

  test('findings report undeclared links, cycles, private names and unused declarations', () => {
    const map = codeMap();
    const findings = window.QualityDashboard.boundaryFindings(map, window.QualityDashboard.aggregateModuleLinks(map));
    expect(findings.undeclared.map((link) => link.source + '>' + link.target)).toEqual(['app.ui>app.api', 'app.api>app.import']);
    expect(findings.cycles.map((link) => [link.source, link.target])).toEqual([['app.api', 'app.import']]);
    expect(findings.privateNames.map((symbol) => symbol.name)).toEqual(['_private']);
    expect(findings.unused.map((link) => link.target)).toEqual(['app.ui']);
  });

  test('dependents sit above their dependencies and contracts between repositories', () => {
    const map = codeMap();
    expect(window.QualityDashboard.moduleLevels(map)).toEqual({ 'app.api': 0, 'app.import': 1, 'app.ui': 0, 'engine.core': 0 });
    const positions = window.QualityDashboard.modulePositions(map);
    expect(positions['app.import'].y).toBeLessThan(positions['app.api'].y);
    expect(positions['engine.core'].x).toBeLessThan(positions['app.api'].x);
    expect(positions['contract:bundle'].x).toBeGreaterThan(positions['engine.core'].x);
    expect(positions['contract:bundle'].x).toBeLessThan(Math.min(positions['app.api'].x, positions['app.ui'].x));
  });

  test('a focused file graph keeps the whole module and marks files entered from outside', () => {
    const graph = window.QualityDashboard.fileGraph(codeMap(), 'app.api');
    expect(graph.files.map((file) => file.id)).toEqual(['app:backend/api.py', 'app:backend/api_helpers.py', 'app:backend/importer.py', 'app:static/js/ui.js']);
    expect(Array.from(graph.entries)).toEqual(['app:backend/api.py']);
    const crossing = graph.links.find((link) => link.source === 'app:backend/api.py' && link.target === 'app:backend/importer.py');
    expect(crossing).toMatchObject({ crossing: true, declared: false });
  });

  test('lane summaries use plain values and never turn missing evidence into a pass', () => {
    const row = report().modules['app.api'];
    const summary = window.QualityDashboard.laneSummary;
    expect(summary(row, 'tests')).toMatchObject({ status: 'pass', text: '12 tests' });
    expect(summary(row, 'coverage')).toMatchObject({ status: 'measured', text: '87.5%', detail: '91% of lines' });
    expect(summary(row, 'duplication')).toMatchObject({ status: 'attention', text: '3', detail: '1 new since the reviewed baseline' });
    expect(summary(row, 'docs')).toMatchObject({ text: '4/4' });
    expect(summary(row, 'dead_code').text).toBe('Not applicable');
    expect(summary({}, 'mutation')).toMatchObject({ status: 'not_measured', text: 'Not measured' });
    expect(summary({ tests: { status: 'surprising' } }, 'tests').status).toBe('not_measured');
  });

  test('node colors follow the chosen encoding', () => {
    const module = codeMap().modules[0];
    const color = window.QualityDashboard.nodeColor;
    expect(color(module, report(), 'criticality')).toBe('#617db5');
    expect(color(module, report(), 'coverage')).toBe('#2d529c');
    expect(color(module, { modules: {} }, 'coverage')).toBe('#e9ecef');
    expect(color(module, report(), 'repository')).toBe('#174092');
  });

  test('escapes catalog text before it reaches the page', () => {
    expect(window.QualityDashboard.escapeHtml('<b title="x">&</b>')).toBe('&lt;b title=&quot;x&quot;&gt;&amp;&lt;/b&gt;');
  });

  describe('functions map', () => {
    test('every function is a node; users count functions and files, links join functions and draw no page links', () => {
      const graph = window.QualityDashboard.symbolGraph(codeMap());
      const byId = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
      expect(graph.nodes).toHaveLength(4);
      expect(byId['app:backend/api.py:serve@3']).toMatchObject({ module: 'app.api', name: 'serve', users: 2, uses: 2 });
      // A page link from importer.py is not a use.
      expect(byId['app:backend/api.py:helper@10']).toMatchObject({ users: 1, uses: 0 });
      expect(byId['app:backend/importer.py:run@5']).toMatchObject({ module: 'app.import', users: 0, uses: 1 });
      const links = Object.fromEntries(graph.links.map((link) => [link.source + '>' + link.target, link]));
      expect(Object.keys(links).sort()).toEqual([
        'app:backend/api.py:serve@3>app:backend/api.py:helper@10',
        'app:backend/api.py:serve@3>app:backend/api_helpers.py:fmt@2',
        'app:backend/importer.py:run@5>app:backend/api.py:serve@3'
      ]);
      expect(links['app:backend/importer.py:run@5>app:backend/api.py:serve@3']).toMatchObject({ crossing: true, declared: true, count: 2, kinds: { calls: 2 } });
      expect(links['app:backend/api.py:serve@3>app:backend/api_helpers.py:fmt@2']).toMatchObject({ crossing: false });
    });

    test('a dot grows with its users, more slowly than their number', () => {
      const size = window.QualityDashboard.symbolSize;
      expect(size(0)).toBe(6);
      expect(size(1)).toBeGreaterThan(size(0));
      expect(size(16)).toBeGreaterThan(size(4));
      expect(size(16) / size(1)).toBeLessThan(16);
    });

    test('modules get distinct palette colours in ring order, the largest the first colour', () => {
      const map = codeMap();
      const ring = window.QualityDashboard.moduleRing(map);
      expect(ring[0]).toBe('engine.core');
      expect(ring.slice(1).sort()).toEqual(['app.api', 'app.import', 'app.ui']);
      const colors = window.QualityDashboard.moduleColors(map);
      expect(colors['app.api']).toBe('#2a78d6');
      expect(new Set(Object.values(colors)).size).toBe(4);
      expect(window.QualityDashboard.moduleColors(map)).toEqual(colors);
      expect(window.QualityDashboard.nodeColor(map.modules[0], report(), 'module', colors)).toBe('#2a78d6');
      expect(window.QualityDashboard.nodeColor(map.modules[0], report(), 'module')).toBe('#e9ecef');
    });

    test('module discs are packed without overlapping, around the middle', () => {
      const radii = [60, 40, 25, 25, 10];
      const centres = window.QualityDashboard.packRegions(radii, 10);
      for (let a = 0; a < radii.length; a++) {
        for (let b = a + 1; b < radii.length; b++) {
          expect(Math.hypot(centres[a].x - centres[b].x, centres[a].y - centres[b].y)).toBeGreaterThan(radii[a] + radii[b] + 9);
        }
      }
      const area = radii.reduce((sum, r) => sum + r * r, 0);
      expect(Math.abs(centres.reduce((sum, centre, k) => sum + centre.x * radii[k] * radii[k], 0) / area)).toBeLessThan(1e-6);
      expect(window.QualityDashboard.packRegions([5])).toEqual([{ x: 0, y: 0 }]);
    });

    test('the layout gives each module its own region of dots that do not overlap, the same every time', () => {
      const map = largeCodeMap(3, 60);
      const graph = window.QualityDashboard.symbolGraph(map);
      const positions = window.QualityDashboard.symbolPositions(map, graph);
      expect(Object.keys(positions)).toHaveLength(180);
      expect(window.QualityDashboard.symbolPositions(map, graph)).toEqual(positions);
      const radius = (node) => window.QualityDashboard.symbolSize(node.users) / 2;
      let closest = Infinity;
      for (let a = 0; a < graph.nodes.length; a++) {
        for (let b = a + 1; b < graph.nodes.length; b++) {
          const [p, q] = [positions[graph.nodes[a].id], positions[graph.nodes[b].id]];
          closest = Math.min(closest, Math.hypot(p.x - q.x, p.y - q.y) / (radius(graph.nodes[a]) + radius(graph.nodes[b])));
        }
      }
      expect(closest).toBeGreaterThan(0.8);
      const centre = {};
      graph.nodes.forEach((node) => {
        const sum = centre[node.module] || (centre[node.module] = { x: 0, y: 0, n: 0 });
        sum.x += positions[node.id].x;
        sum.y += positions[node.id].y;
        sum.n += 1;
      });
      const nearest = (point) => Object.keys(centre).sort((a, b) => Math.hypot(point.x - centre[a].x / centre[a].n, point.y - centre[a].y / centre[a].n)
        - Math.hypot(point.x - centre[b].x / centre[b].n, point.y - centre[b].y / centre[b].n))[0];
      const inOwnRegion = graph.nodes.filter((node) => nearest(positions[node.id]) === node.module).length;
      expect(inOwnRegion / graph.nodes.length).toBeGreaterThan(0.95);
      expect(window.QualityDashboard.symbolPositions({ modules: [] }, { nodes: [], links: [] })).toEqual({});
    });

    test('search ranks the exact name, then a prefix, then a part of the name, then the path', () => {
      const graph = window.QualityDashboard.symbolGraph(codeMap());
      const match = window.QualityDashboard.matchSymbols;
      expect(match(graph, '  ')).toEqual([]);
      expect(match(graph, 'serve')[0]).toEqual({ kind: 'symbol', id: 'app:backend/api.py:serve@3', name: 'serve', detail: 'backend/api.py:3' });
      expect(match(graph, 'help').map((row) => row.kind + ' ' + row.name)).toEqual(['symbol helper', 'file api_helpers.py', 'symbol fmt']);
      // Files with more functions come first among equal matches; case does not matter.
      expect(match(graph, 'API').slice(0, 2).map((row) => row.id)).toEqual(['app:backend/api.py', 'app:backend/api_helpers.py']);
      expect(match(graph, 'API')[0].detail).toBe('backend/api.py · 2 functions and classes');
      expect(match(graph, 'a', 2)).toHaveLength(2);
      expect(match(graph, 'nothing-like-this')).toEqual([]);
    });

    test('names show from the largest dot down, never over another name, and a selection is always named', () => {
      const node = (id, users, name) => ({ id, name: name || id, users });
      const map = {
        graph: { nodes: [node('big', 25, 'big_name'), node('near', 9, 'near_name'), node('far', 9), node('small', 0)] },
        positions: { big: { x: 0, y: 0 }, near: { x: 0, y: -40 }, far: { x: 500, y: 0 }, small: { x: 900, y: 0 } }
      };
      const measure = (label, size) => label.length * size * 0.6;
      const places = window.QualityDashboard.labelPlaces;
      const ids = (rows) => rows.map((row) => row.id);
      // Zoomed out only the largest dot qualifies; closer in, the dot just above 'big' puts its name above itself, since
      // below it the name would run into 'big'.
      expect(ids(places(map, 0.65, { measure }))).toEqual(['big']);
      const closer = places(map, 1, { measure });
      expect(ids(closer)).toEqual(['big', 'far', 'near']);
      expect(closer.map((row) => row.above)).toEqual([false, false, true]);
      expect(ids(places(map, 3, { measure }))).toContain('small');
      const selected = places(map, 0.2, { measure, only: new Set(['near', 'small']), first: 'small' });
      expect(ids(selected)).toEqual(['small', 'near']);
      // Zoomed in, a name stays at most LABEL_MAX_PX on screen, so it takes less of the map and two crowded names fit.
      const crowded = {
        graph: { nodes: [node('one', 20, 'first_long_name'), node('two', 20, 'second_long_name')] },
        positions: { one: { x: 0, y: 0 }, two: { x: 0, y: 10 } }
      };
      expect(ids(places(crowded, 1, { measure }))).toEqual(['one']);
      const zoomed = places(crowded, 6, { measure });
      expect(ids(zoomed)).toEqual(['one', 'two']);
      expect(zoomed[0].font * 6).toBeCloseTo(13, 0);
    });
  });

  describe('page', () => {
    function pageHtml() {
      return `
        <div id="qualityDashboard" data-api-url="/api/quality">
          <dl id="qualitySummary"></dl>
          <div id="qualityWarning" hidden><span id="qualityWarningText"></span></div>
          <div id="qualityUnavailable" hidden></div>
          <div id="qualityContent" hidden>
            <section id="qualityMapSection">
              <div class="quality-workspace">
                <span id="qualityBreadcrumb"></span>
                <button data-view-toggle="modules"></button><button data-view-toggle="files"></button><button data-view-toggle="symbols"></button>
                <div id="qualityColorBy"><button data-color-by="module" hidden></button><button data-color-by="criticality"></button><button data-color-by="coverage"></button></div>
                <input type="checkbox" id="qualityUnusedToggle" checked>
                <button id="qualityPanelToggle" aria-pressed="true"></button>
                <button id="qualityFullscreen" aria-pressed="false"><i class="fas fa-expand"></i><span class="quality-tool__text">Expand</span></button>
                <aside id="qualityExplorer" hidden>
                  <input type="search" id="qualitySearch"><ul id="qualitySearchResults" hidden></ul>
                  <input type="checkbox" id="qualityEdgesToggle" checked><input type="checkbox" id="qualityLabelsToggle" checked>
                  <button id="qualityExplorerReset" data-symbol-reset></button><ul id="qualityExplorerModules"></ul>
                </aside>
                <div class="quality-map-stage">
                  <div id="qualityMap"></div><div id="qualityTooltip" hidden></div><div id="qualityZoomHint"></div>
                  <button id="qualityFit"></button>
                </div>
                <aside id="qualityPanel"></aside>
                <ul id="qualityLegend"></ul>
              </div>
            </section>
            <section id="qualityFindingsSection"><div id="qualityFindings"></div></section>
            <section id="qualityBlindSpotsSection"><div id="qualityBlindSpots"></div></section>
            <table><tbody id="qualityTable"></tbody></table>
            <div id="qualityChecks"></div>
          </div>
        </div>`;
    }

    function fakeCytoscape() {
      const collection = () => {
        const items = [];
        return Object.assign(items, {
          remove: jest.fn(), removeClass: jest.fn(), unselect: jest.fn(), forEach: Array.prototype.forEach.bind(items), length: 0
        });
      };
      const instance = {
        elements: jest.fn(collection), nodes: jest.fn(collection), add: jest.fn(), on: jest.fn(), fit: jest.fn(),
        getElementById: jest.fn(collection), layout: jest.fn(() => ({ run: jest.fn() }))
      };
      window.cytoscape = jest.fn(() => instance);
      return instance;
    }

    function respond(data) {
      global.fetch = jest.fn(() => Promise.resolve({ json: () => Promise.resolve(data) }));
    }

    beforeEach(() => {
      document.body.innerHTML = pageHtml();
    });

    afterEach(() => {
      delete global.fetch;
      delete window.cytoscape;
    });

    test('renders the summary, findings, table and preset module layout', async () => {
      const cy = fakeCytoscape();
      respond({ available: true, warning: null, run_url: 'https://ci/run', source_urls: { app: 'https://github.com/x/app/blob/sha/' }, report: report(), code_map: codeMap() });
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));

      expect(document.getElementById('qualityContent').hidden).toBe(false);
      expect(document.getElementById('qualitySummary').textContent).toContain('1 of 2 passed');
      expect(document.querySelector('#qualitySummary a[href="https://github.com/x/app/commit/' + 'a'.repeat(40) + '"]')).not.toBeNull();
      expect(document.getElementById('qualityFindings').textContent).toContain('_private');
      const spots = document.getElementById('qualityBlindSpots').textContent;
      expect(spots).toContain('/api/missing');
      expect(spots).toContain('/api/old');
      expect(spots).toContain('config.url');
      expect(spots).toContain('Static reading only.');
      expect(document.querySelectorAll('#qualityTable tr')).toHaveLength(2);
      expect(document.getElementById('qualityTable').textContent).toContain('87.5%');
      expect(document.getElementById('qualityPanel').textContent).toContain('How to read the map');
      expect(cy.layout).toHaveBeenCalledWith(expect.objectContaining({ name: 'preset' }));
      const added = cy.add.mock.calls[0][0];
      expect(added.find((item) => item.data.id === 'link:app.api>app.import').classes).toBe('undeclared');
      expect(added.find((item) => item.data.id === 'link:app.import>app.ui').classes).toBe('unused');
    });

    test('a stale report shows its warning', async () => {
      fakeCytoscape();
      respond({ available: true, warning: 'Measured on an older commit.', report: report(), code_map: codeMap() });
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      expect(document.getElementById('qualityWarning').hidden).toBe(false);
      expect(document.getElementById('qualityWarningText').textContent).toBe('Measured on an older commit.');
    });

    test('a report without a map keeps the evidence table', async () => {
      respond({ available: true, report: report(), code_map: null });
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      expect(document.getElementById('qualityMapSection').hidden).toBe(true);
      expect(document.querySelectorAll('#qualityTable tr')).toHaveLength(2);
    });

    /** A Cytoscape stand-in that keeps the added elements, their classes and the selection. */
    function graphCytoscape() {
      let items = [];
      const element = (definition) => {
        const classes = new Set(String(definition.classes || '').split(/\s+/).filter(Boolean));
        const self = {
          definition, classes, selected: false,
          id: () => definition.data.id,
          data: (key) => (key === undefined ? definition.data : typeof key === 'object' ? Object.assign(definition.data, key) : definition.data[key]),
          isNode: () => definition.group === 'nodes',
          hasClass: (name) => classes.has(name)
        };
        return self;
      };
      const matches = (item, selector) => !selector || selector.split(',').some((part) => (part.match(/\.[\w-]+/g) || []).every((name) => item.classes.has(name.slice(1))));
      const collection = (list) => {
        const each = (fn) => { list.forEach(fn); return api; };
        const ids = (other) => new Set(other.list.map((item) => item.id()));
        const api = {
          list, length: list.length,
          forEach: (fn) => list.forEach((item) => fn(api.wrap(item))),
          map: (fn) => list.map((item) => fn(api.wrap(item))),
          filter: (fn) => collection(list.filter((item) => fn(api.wrap(item)))),
          wrap: (item) => Object.assign(collection([item]), { id: item.id, data: item.data }),
          id: () => list[0] && list[0].id(),
          data: (key) => list[0] && list[0].data(key),
          isNode: () => Boolean(list[0] && list[0].isNode()),
          isParent: () => false,
          removed: () => false,
          hasClass: (name) => Boolean(list[0] && list[0].hasClass(name)),
          addClass: (names) => each((item) => names.split(' ').forEach((name) => item.classes.add(name))),
          removeClass: (names) => each((item) => names.split(' ').forEach((name) => item.classes.delete(name))),
          toggleClass: (name, on) => each((item) => (on ? item.classes.add(name) : item.classes.delete(name))),
          select: () => each((item) => { item.selected = true; }),
          unselect: () => each((item) => { item.selected = false; }),
          remove: () => { items = items.filter((item) => !list.includes(item)); },
          nodes: () => collection(list.filter((item) => item.isNode())),
          edges: () => collection(list.filter((item) => !item.isNode())),
          union: (other) => collection(Array.from(new Set(list.concat(other.list)))),
          not: (other) => collection(list.filter((item) => !ids(other).has(item.id()))),
          ancestors: () => collection([]),
          descendants: () => collection([]),
          connectedEdges: () => collection(items.filter((item) => !item.isNode() && list.some((end) => [item.data('source'), item.data('target')].includes(end.id())))),
          closedNeighborhood: () => {
            const edges = api.connectedEdges().list;
            const ends = new Set(edges.flatMap((edge) => [edge.data('source'), edge.data('target')]));
            return collection(Array.from(new Set(list.concat(edges, items.filter((item) => item.isNode() && ends.has(item.id()))))));
          }
        };
        return api;
      };
      const instance = {
        add: jest.fn((definitions) => { items = items.concat(definitions.map(element)); }),
        elements: (selector) => collection(items.filter((item) => matches(item, selector))),
        nodes: (selector) => collection(items.filter((item) => item.isNode() && matches(item, selector))),
        edges: (selector) => collection(items.filter((item) => !item.isNode() && matches(item, selector))),
        $: () => collection(items.filter((item) => item.selected)),
        getElementById: (id) => collection(items.filter((item) => item.id() === id)),
        on: jest.fn(), fit: jest.fn(), resize: jest.fn(), center: jest.fn(), animate: jest.fn(),
        zoom: jest.fn(() => 1), batch: (fn) => fn(), layout: jest.fn(() => ({ run: jest.fn() }))
      };
      window.cytoscape = jest.fn(() => instance);
      return instance;
    }

    const nextFrame = () => new Promise((resolve) => window.requestAnimationFrame(resolve));
    const click = (selector) => document.querySelector(selector).dispatchEvent(new MouseEvent('click', { bubbles: true }));

    describe('functions map', () => {
      let getContext;
      beforeEach(() => {
        // JSDOM has no canvas: label widths fall back to an estimate.
        getContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = () => null;
      });
      afterEach(() => {
        HTMLCanvasElement.prototype.getContext = getContext;
      });

      async function openFunctions() {
        const cy = graphCytoscape();
        respond({ available: true, report: report(), code_map: codeMap() });
        await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
        click('[data-view-toggle="symbols"]');
        await nextFrame();
        return cy;
      }

      test('draws every function coloured by module, with the module list and its own controls', async () => {
        const cy = await openFunctions();
        const symbols = cy.nodes('.symbol');
        expect(symbols.length).toBe(4);
        expect(cy.edges('.symbol-link').length).toBe(3);
        expect(cy.getElementById('app:backend/api.py:serve@3').data('color')).toBe('#2a78d6');
        expect(document.getElementById('qualityExplorer').hidden).toBe(false);
        expect(cy.resize).toHaveBeenCalled();
        const modules = document.querySelectorAll('[data-symbol-module]');
        expect(Array.from(modules).map((button) => button.textContent)).toEqual(['api3', 'import1']);
        expect(document.querySelector('[data-view-toggle="symbols"]').getAttribute('aria-pressed')).toBe('true');
        expect(document.querySelector('[data-color-by="module"]').hidden).toBe(false);
        expect(document.querySelector('[data-color-by="module"]').getAttribute('aria-pressed')).toBe('true');
        expect(document.getElementById('qualityPanel').textContent).toContain('How to read the functions map');
        expect(document.getElementById('qualityLegend').textContent).toContain('Dot size');
        expect(document.getElementById('qualityBreadcrumb').textContent).toContain('All functions');

        document.getElementById('qualityEdgesToggle').checked = false;
        document.getElementById('qualityEdgesToggle').dispatchEvent(new Event('change'));
        expect(cy.edges('.symbol-link.hidden').length).toBe(3);
        document.getElementById('qualityLabelsToggle').checked = false;
        document.getElementById('qualityLabelsToggle').dispatchEvent(new Event('change'));
        expect(cy.nodes('.symbol.unlabelled').length).toBe(4);

        click('[data-color-by="criticality"]');
        expect(cy.getElementById('app:backend/api.py:serve@3').data('color')).toBe('#617db5');
        click('[data-view-toggle="modules"]');
        await nextFrame();
        expect(document.getElementById('qualityExplorer').hidden).toBe(true);
        expect(document.querySelector('[data-color-by="module"]').hidden).toBe(true);
        expect(document.querySelector('[data-color-by="criticality"]').getAttribute('aria-pressed')).toBe('true');
      });

      test('a module picked from the list fades the other functions until it is picked again', async () => {
        const cy = await openFunctions();
        click('[data-symbol-module="app.api"]');
        expect(document.querySelector('[data-symbol-module="app.api"]').getAttribute('aria-pressed')).toBe('true');
        expect(document.getElementById('qualityPanel').textContent).toContain('Serve data.');
        expect(cy.nodes('.symbol.faded').map((node) => node.id())).toEqual(['app:backend/importer.py:run@5']);
        click('[data-symbol-module="app.api"]');
        expect(cy.nodes('.symbol.faded').length).toBe(0);
        expect(document.getElementById('qualityPanel').textContent).toContain('How to read the functions map');
      });

      test('the details panel hides to widen the map and opens again on a selection', async () => {
        const cy = await openFunctions();
        const workspace = document.querySelector('.quality-workspace');
        const toggle = document.getElementById('qualityPanelToggle');
        cy.resize.mockClear();
        click('#qualityPanelToggle');
        expect(workspace.classList.contains('is-panel-hidden')).toBe(true);
        expect(toggle.getAttribute('aria-pressed')).toBe('false');
        expect(toggle.title).toBe('Show the details panel');
        expect(cy.resize).toHaveBeenCalledTimes(1);
        const search = document.getElementById('qualitySearch');
        search.value = 'serv';
        search.dispatchEvent(new Event('input'));
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        expect(workspace.classList.contains('is-panel-hidden')).toBe(false);
        expect(toggle.getAttribute('aria-pressed')).toBe('true');
        expect(document.getElementById('qualityPanel').textContent).toContain('Open file functions');
      });

      test('search selects the match and shows its callers and callees; Esc then clears it', async () => {
        const cy = await openFunctions();
        const search = document.getElementById('qualitySearch');
        search.value = 'serv';
        search.dispatchEvent(new Event('input'));
        const results = document.getElementById('qualitySearchResults');
        expect(results.hidden).toBe(false);
        expect(results.querySelector('[role="option"]').textContent).toContain('serve');
        expect(search.getAttribute('aria-activedescendant')).toBe('qualitySearchOption0');
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        expect(results.hidden).toBe(true);
        expect(cy.$(':selected').id()).toBe('app:backend/api.py:serve@3');
        expect(cy.animate).toHaveBeenCalled();
        const panel = document.getElementById('qualityPanel').textContent;
        expect(panel).toContain('Open file functions');
        expect(panel).toContain('run');
        expect(cy.nodes('.symbol.faded').length).toBe(0);
        expect(cy.nodes('.symbol.named').length).toBeGreaterThan(0);
        // The first Esc empties the box, the next one clears the selection.
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        expect(search.value).toBe('');
        expect(cy.$(':selected').length).toBe(1);
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        expect(cy.$(':selected').length).toBe(0);
      });

      test('a file found by search selects all its functions', async () => {
        const cy = await openFunctions();
        const search = document.getElementById('qualitySearch');
        search.value = 'api.py';
        search.dispatchEvent(new Event('input'));
        click('#qualitySearchOption0');
        expect(cy.$(':selected').map((node) => node.id()).sort()).toEqual(['app:backend/api.py:helper@10', 'app:backend/api.py:serve@3']);
        expect(document.getElementById('qualityPanel').textContent).toContain('Open file functions');
      });

      test('opening a function\'s file from the map goes back to the map with Esc', async () => {
        await openFunctions();
        click('[data-symbol-module="app.import"]');
        click('[data-symbol-module="app.import"]');
        const search = document.getElementById('qualitySearch');
        search.value = 'run';
        search.dispatchEvent(new Event('input'));
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        click('#qualityPanel [data-open-file]');
        await nextFrame();
        expect(document.getElementById('qualityBreadcrumb').textContent).toContain('All functions');
        expect(document.querySelector('[data-view-toggle="symbols"]').getAttribute('aria-pressed')).toBe('true');
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        await nextFrame();
        expect(document.getElementById('qualityExplorer').hidden).toBe(false);
      });
    });

    test('the expand button fills the window below the navbar and Esc returns to the page', async () => {
      const cy = fakeCytoscape();
      cy.resize = jest.fn();
      respond({ available: true, report: report(), code_map: codeMap() });
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      const workspace = document.querySelector('.quality-workspace');
      const button = document.getElementById('qualityFullscreen');
      click('#qualityFullscreen');
      expect(workspace.classList.contains('is-expanded')).toBe(true);
      expect(workspace.style.getPropertyValue('--quality-expanded-top')).toBe('0px');
      expect(document.documentElement.classList.contains('quality-scroll-locked')).toBe(true);
      expect(button.getAttribute('aria-pressed')).toBe('true');
      expect(button.getAttribute('aria-label')).toBe('Back to the page');
      expect(button.querySelector('i').className).toBe('fas fa-compress');
      expect(button.textContent).toBe('Exit');
      expect(cy.resize).toHaveBeenCalledTimes(1);
      expect(cy.fit).toHaveBeenCalled();
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
      expect(workspace.classList.contains('is-expanded')).toBe(false);
      expect(document.documentElement.classList.contains('quality-scroll-locked')).toBe(false);
      expect(button.getAttribute('aria-pressed')).toBe('false');
      expect(button.getAttribute('aria-label')).toBe('Expand the map to the window');
      expect(button.querySelector('i').className).toBe('fas fa-expand');
      expect(button.textContent).toBe('Expand');
      click('#qualityFullscreen');
      click('#qualityFullscreen');
      expect(workspace.classList.contains('is-expanded')).toBe(false);
      expect(cy.resize).toHaveBeenCalledTimes(4);
    });

    test('missing evidence or a failed request is shown as unavailable', async () => {
      respond({ available: false });
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      expect(document.getElementById('qualityUnavailable').hidden).toBe(false);
      document.body.innerHTML = pageHtml();
      global.fetch = jest.fn(() => Promise.reject(new Error('offline')));
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      expect(document.getElementById('qualityUnavailable').hidden).toBe(false);
      expect(document.getElementById('qualityContent').hidden).toBe(true);
    });
  });
});
