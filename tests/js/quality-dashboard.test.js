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
      { id: 'app:backend/importer.py:run@5', name: 'run', file: 'app:backend/importer.py', line: 5, unused: true }
    ],
    clones: [{ files: ['app:backend/api.py', 'app:backend/importer.py'], lines: 14,
      locations: [{ file: 'app:backend/api.py', start: 30, end: 43 }, { file: 'app:backend/importer.py', start: 5, end: 18 }] }],
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
    completeness: 'complete', generated_at: '2026-11-01T10:00:00+00:00', revision: { app: 'a'.repeat(40), engine: 'b'.repeat(40) },
    checks: [{ name: 'app-python-tests', status: 'pass' }, { name: 'engine-tests', status: 'fail' }],
    modules: {
      'app.api': { criticality: 'high', tests: { status: 'pass', count: 12, skipped: 0, missing_files: [] }, coverage: { status: 'measured', branches: 87.5, lines: 91 },
        duplication: { status: 'attention', count: 3, new: 1 },
        docs: { status: 'pass', satisfied: 4, required: 4 }, architecture: { status: 'pass', violations: [] } },
      'app.import': { criticality: 'critical', tests: { status: 'fail', count: 1 }, coverage: { status: 'measured', branches: 12 } }
    },
    files: { 'app:backend/api.py': { lines: 95, branches: 90 }, 'app:backend/api_helpers.py': { lines: 40, branches: null } }
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
    ['code-map', 'rendering', 'dashboard'].forEach((name) => loadBrowserScript(path.join(__dirname, '../../static/js/quality', name + '.js')));
  });

  test('module links separate declared, undeclared and code-free dependencies', () => {
    const links = window.QualityMap.aggregateModuleLinks(codeMap());
    const byKey = Object.fromEntries(links.map((link) => [link.source + '>' + link.target, link]));
    expect(byKey['app.import>app.api']).toMatchObject({ count: 5, declared: true, kinds: { imports: 2, calls: 3 } });
    expect(byKey['app.api>app.import']).toMatchObject({ count: 1, declared: false });
    expect(byKey['app.import>app.ui']).toMatchObject({ count: 0, declared: true });
    expect(links.some((link) => link.source === link.target)).toBe(false);
  });

  test('HTTP requests draw arrows, links to pages do not', () => {
    const links = window.QualityMap.aggregateModuleLinks(codeMap());
    const byKey = Object.fromEntries(links.map((link) => [link.source + '>' + link.target, link]));
    expect(byKey['app.ui>app.api']).toMatchObject({ count: 2, declared: false, kinds: { requests: 2 } });
    expect(byKey['app.import>app.ui']).toMatchObject({ count: 0, declared: true });
    const crossing = window.QualityMap.fileLinks(codeMap()).find((link) => link.source === 'app:backend/api.py' && link.target === 'app:backend/importer.py');
    expect(crossing).toMatchObject({ count: 1, crossing: true, declared: false });
  });

  test('blind spots list unmatched references, unreached routes, runtime URLs and shared names', () => {
    const spots = window.QualityMap.blindSpots(codeMap());
    expect(spots.unmatched.map((row) => row.reference)).toEqual(['/api/missing']);
    expect(spots.unreached.map((route) => route.pattern)).toEqual(['/api/old']);
    expect(spots.dynamic.map((row) => row.expression)).toEqual(['config.url']);
    expect(spots.sharedNames.map((row) => row.name)).toEqual(['helper']);
    expect(window.QualityMap.blindSpots({ files: [], links: [] })).toEqual({ unmatched: [], unreached: [], dynamic: [], sharedNames: [] });
  });

  test('findings report undeclared links, cycles, private names and unused declarations', () => {
    const map = codeMap();
    const findings = window.QualityMap.boundaryFindings(map, window.QualityMap.aggregateModuleLinks(map));
    expect(findings.undeclared.map((link) => link.source + '>' + link.target)).toEqual(['app.ui>app.api', 'app.api>app.import']);
    expect(findings.cycles.map((link) => [link.source, link.target])).toEqual([['app.api', 'app.import']]);
    expect(findings.privateNames.map((symbol) => symbol.name)).toEqual(['_private']);
    expect(findings.unused.map((link) => link.target)).toEqual(['app.ui']);
  });

  test('cleanup candidates are functions nothing mentions, copied blocks and long code files', () => {
    const map = codeMap();
    map.files.push({ id: 'app:package-lock.json', module: 'app.ui', lines: 9000, symbols: 0 });
    const tidy = window.QualityMap.cleanup(map);
    expect(tidy.unused.map((symbol) => symbol.name)).toEqual(['run']);
    expect(tidy.clones).toHaveLength(1);
    // A lock file is long but is no code to tidy.
    expect(tidy.large.map((file) => file.id)).toEqual(['engine:src/core.py']);
    expect(window.QualityMap.cleanup({ files: [] })).toEqual({ unused: [], clones: [], large: [] });
  });

  test('a module sits above its dependencies, each repository in its own column, on one bottom line', () => {
    const map = codeMap();
    expect(window.QualityMap.moduleLevels(map)).toEqual({ 'app.api': 0, 'app.import': 1, 'app.ui': 0, 'engine.core': 0 });
    expect(window.QualityMap.moduleColumns(map)).toEqual({ 'app.api': 0, 'app.import': 0, 'app.ui': 0, 'engine.core': 1 });
    const radii = { 'app.api': 50, 'app.import': 30, 'app.ui': 20, 'engine.core': 40 };
    const at = window.QualityMap.layeredCentres(map, radii);
    expect(at['app.import'].y + radii['app.import']).toBeLessThan(at['app.api'].y - radii['app.api']);
    // Modules of the same level sit side by side without touching.
    expect(at['app.ui'].y).toBe(at['app.api'].y);
    expect(Math.abs(at['app.ui'].x - at['app.api'].x)).toBeGreaterThan(radii['app.api'] + radii['app.ui']);
    expect(at['engine.core'].x - radii['engine.core']).toBeGreaterThan(Math.max(at['app.api'].x + radii['app.api'], at['app.ui'].x + radii['app.ui']));
    expect(at['engine.core'].y + radii['engine.core']).toBe(at['app.api'].y + radii['app.api']);
    // The list beside the map follows the same order: a repository after the other, each from its top module down.
    expect(window.QualityMap.moduleHierarchy(map)).toEqual(['app.import', 'app.api', 'app.ui', 'engine.core']);
  });

  test('on Functions the module circles are piled: a module above its dependencies, the repositories side by side', () => {
    const map = codeMap();
    const radii = { 'app.api': 120, 'app.import': 60, 'app.ui': 40, 'engine.core': 90 };
    const at = window.QualityMap.stackedCentres(map, radii, 10);
    const ids = Object.keys(radii);
    ids.forEach((a) => ids.forEach((b) => {
      if (a < b) expect(Math.hypot(at[a].x - at[b].x, at[a].y - at[b].y)).toBeGreaterThanOrEqual(radii[a] + radii[b] + 9);
    }));
    // The importer rests on the API it depends on, higher up; the unrelated module stands on the floor beside it.
    expect(at['app.import'].y).toBeLessThan(at['app.api'].y);
    expect(at['app.ui'].y + radii['app.ui']).toBe(at['app.api'].y + radii['app.api']);
    expect(at['engine.core'].y + radii['engine.core']).toBe(at['app.api'].y + radii['app.api']);
    ['app.api', 'app.import', 'app.ui'].forEach((id) => expect(at[id].x + radii[id]).toBeLessThan(at['engine.core'].x - radii['engine.core']));
    // A pile is lower than the column the same circles would make.
    expect(at['app.api'].y - at['app.import'].y).toBeLessThan(radii['app.api'] + radii['app.import']);
    expect(window.QualityMap.stackedCentres(map, radii, 10)).toEqual(at);
  });

  test('lane summaries use plain values and never turn missing evidence into a pass', () => {
    const row = report().modules['app.api'];
    const summary = window.QualityRendering.laneSummary;
    expect(summary(row, 'tests')).toMatchObject({ status: 'pass', text: '12 tests' });
    expect(summary(row, 'coverage')).toMatchObject({ status: 'measured', text: '87.5%', detail: '91% of lines' });
    expect(summary(row, 'duplication')).toMatchObject({ status: 'attention', text: '3', detail: '1 new since the reviewed baseline' });
    expect(summary(row, 'docs')).toMatchObject({ text: '4/4' });
    expect(summary({}, 'coverage')).toMatchObject({ status: 'not_measured', text: 'Not measured' });
    expect(summary(undefined, 'tests')).toMatchObject({ status: 'not_measured' });
    expect(summary({ tests: { status: 'surprising' } }, 'tests').status).toBe('not_measured');
  });

  test('colours follow the chosen encoding, and coverage is a file\'s own', () => {
    const module = codeMap().modules[0];
    const color = window.QualityRendering.nodeColor;
    expect(color(module, report(), 'criticality')).toBe('#617db5');
    expect(color(module, report(), 'coverage')).toBe('#2d529c');
    expect(color(module, { modules: {} }, 'coverage')).toBe('#e9ecef');
    expect(color(module, report(), 'repository')).toBe('#174092');
    // A file is painted with its own branch coverage, or its line coverage when it has no branches.
    expect(color(module, report(), 'coverage', null, 'app:backend/api.py')).toBe('#174092');
    expect(color(module, report(), 'coverage', null, 'app:backend/api_helpers.py')).not.toBe('#e9ecef');
    expect(color(module, report(), 'coverage', null, 'app:backend/api_helpers.py')).not.toBe('#174092');
    expect(color(module, report(), 'coverage', null, 'app:backend/unmeasured.css')).toBe('#e9ecef');
    expect(color(undefined, report(), 'module', {})).toBe('#e9ecef');
  });

  test('escapes catalog text before it reaches the page', () => {
    expect(window.QualityRendering.escapeHtml('<b title="x">&</b>')).toBe('&lt;b title=&quot;x&quot;&gt;&amp;&lt;/b&gt;');
  });

  describe('dots and circles', () => {
    test('every function is a node; users count functions and files, links join functions and draw no page links', () => {
      const graph = window.QualityMap.symbolGraph(codeMap());
      const byId = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
      expect(graph.nodes).toHaveLength(4);
      expect(byId['app:backend/api.py:serve@3']).toMatchObject({ module: 'app.api', name: 'serve', users: 2, uses: 2 });
      // A page link from importer.py is not a use.
      expect(byId['app:backend/api.py:helper@10']).toMatchObject({ users: 1, uses: 0 });
      expect(byId['app:backend/importer.py:run@5']).toMatchObject({ module: 'app.import', users: 0, uses: 1, unused: true, size: 6 });
      expect(byId['app:backend/api.py:serve@3']).toMatchObject({ kind: 'symbol', group: 'app:backend/api.py', unused: false });
      const links = Object.fromEntries(graph.links.map((link) => [link.source + '>' + link.target, link]));
      expect(Object.keys(links).sort()).toEqual([
        'app:backend/api.py:serve@3>app:backend/api.py:helper@10',
        'app:backend/api.py:serve@3>app:backend/api_helpers.py:fmt@2',
        'app:backend/importer.py:run@5>app:backend/api.py:serve@3'
      ]);
      expect(links['app:backend/importer.py:run@5>app:backend/api.py:serve@3']).toMatchObject({ crossing: true, declared: true, count: 2, kinds: { calls: 2 } });
      expect(links['app:backend/api.py:serve@3>app:backend/api_helpers.py:fmt@2']).toMatchObject({ crossing: false });
    });

    test('a module alone keeps its functions, their sizes and the links between them, and nothing else', () => {
      const graph = window.QualityMap.symbolGraph(codeMap());
      const api = window.QualityMap.moduleSymbolGraph(graph, 'app.api');
      expect(api.nodes.map((node) => node.id).sort()).toEqual(['app:backend/api.py:helper@10', 'app:backend/api.py:serve@3', 'app:backend/api_helpers.py:fmt@2']);
      // serve keeps the user it has in another module, so its dot is as large as on the whole map.
      expect(api.nodes.find((node) => node.name === 'serve').users).toBe(2);
      expect(api.links.map((link) => link.source + '>' + link.target).sort()).toEqual([
        'app:backend/api.py:serve@3>app:backend/api.py:helper@10',
        'app:backend/api.py:serve@3>app:backend/api_helpers.py:fmt@2'
      ]);
      const { positions } = window.QualityMap.dotLayout(api);
      expect(Object.keys(positions).sort()).toEqual(api.nodes.map((node) => node.id).sort());
      expect(window.QualityMap.moduleSymbolGraph(graph, 'app.ui')).toEqual({ nodes: [], links: [] });
    });

    test('a dot grows with its users, more slowly than their number', () => {
      const size = window.QualityMap.symbolSize;
      expect(size(0)).toBe(6);
      expect(size(1)).toBeGreaterThan(size(0));
      expect(size(16)).toBeGreaterThan(size(4));
      expect(size(16) / size(1)).toBeLessThan(16);
    });

    test('modules get the palette colours in the order of the hierarchy', () => {
      const map = codeMap();
      const colors = window.QualityMap.moduleColors(map);
      expect(colors).toEqual({ 'app.import': '#2a78d6', 'app.api': '#eb6834', 'app.ui': '#17a173', 'engine.core': '#99631f' });
      expect(window.QualityRendering.nodeColor(map.modules[0], report(), 'module', colors)).toBe('#eb6834');
      expect(window.QualityRendering.nodeColor(map.modules[0], report(), 'module')).toBe('#e9ecef');
    });

    test('module discs are packed without overlapping, around the middle', () => {
      const radii = [60, 40, 25, 25, 10];
      const centres = window.QualityMap.packRegions(radii, 10);
      for (let a = 0; a < radii.length; a++) {
        for (let b = a + 1; b < radii.length; b++) {
          expect(Math.hypot(centres[a].x - centres[b].x, centres[a].y - centres[b].y)).toBeGreaterThan(radii[a] + radii[b] + 9);
        }
      }
      const area = radii.reduce((sum, r) => sum + r * r, 0);
      expect(Math.abs(centres.reduce((sum, centre, k) => sum + centre.x * radii[k] * radii[k], 0) / area)).toBeLessThan(1e-6);
      expect(window.QualityMap.packRegions([5])).toEqual([{ x: 0, y: 0 }]);
    });

    test('the layout gives each module its own region of dots that do not overlap, the same every time', () => {
      const map = largeCodeMap(3, 60);
      const graph = window.QualityMap.symbolGraph(map);
      const { positions } = window.QualityMap.dotLayout(graph);
      expect(Object.keys(positions)).toHaveLength(180);
      expect(window.QualityMap.dotLayout(graph).positions).toEqual(positions);
      const radius = (node) => node.size / 2;
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
      expect(window.QualityMap.dotLayout({ nodes: [], links: [] })).toEqual({ positions: {}, regions: [] });
    });

    test('each region is a circle around its own dots that no other circle reaches, and dots keep room between them', () => {
      const map = largeCodeMap(3, 60);
      const radius = (node) => node.size / 2;
      const check = (graph, regionOf) => {
        const { positions, regions } = window.QualityMap.dotLayout(graph, { regionOf });
        const byId = Object.fromEntries(regions.map((region) => [region.id, region]));
        expect(Object.keys(byId).sort()).toEqual(Array.from(new Set(graph.nodes.map(regionOf))).sort());
        expect(regions.map((region) => region.count)).toEqual(regions.map((region) => region.count).sort((a, b) => b - a));
        graph.nodes.forEach((node) => {
          const circle = byId[regionOf(node)];
          expect(Math.hypot(positions[node.id].x - circle.x, positions[node.id].y - circle.y) + radius(node)).toBeLessThanOrEqual(circle.r);
        });
        for (let a = 0; a < regions.length; a++) {
          for (let b = a + 1; b < regions.length; b++) {
            expect(Math.hypot(regions[a].x - regions[b].x, regions[a].y - regions[b].y)).toBeGreaterThan(regions[a].r + regions[b].r);
          }
        }
        let closest = Infinity;
        for (let a = 0; a < graph.nodes.length; a++) {
          for (let b = a + 1; b < graph.nodes.length; b++) {
            const [p, q] = [positions[graph.nodes[a].id], positions[graph.nodes[b].id]];
            closest = Math.min(closest, Math.hypot(p.x - q.x, p.y - q.y) / (radius(graph.nodes[a]) + radius(graph.nodes[b])));
          }
        }
        // Each dot keeps DOT_ROOM (0.6) of its radius clear, so neighbours sit well apart, not edge to edge.
        expect(closest).toBeGreaterThan(1.4);
      };
      const graph = window.QualityMap.symbolGraph(map);
      check(graph, (node) => node.module);
      // A module drawn alone has a circle for each of its four files.
      const alone = window.QualityMap.moduleSymbolGraph(graph, 'app.m1');
      check(alone, (node) => node.file);
      expect(window.QualityMap.dotLayout(alone, { regionOf: (node) => node.file }).regions).toHaveLength(4);
    });

    test('every file is a dot sized by its lines, in its folder\'s group, and page links draw nothing', () => {
      const graph = window.QualityMap.fileDots(codeMap());
      const byId = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
      expect(graph.nodes).toHaveLength(5);
      expect(byId['app:backend/api.py']).toMatchObject({ kind: 'file', name: 'api.py', module: 'app.api', lines: 400, group: 'app:backend/', large: false });
      expect(byId['engine:src/core.py'].large).toBe(true);
      expect(byId['engine:src/core.py'].size).toBeGreaterThan(byId['app:backend/api.py'].size);
      const size = window.QualityMap.fileSize;
      expect(size(0)).toBe(5);
      // A generated file of any length is no larger than one of 3,000 lines.
      expect(size(90000)).toBe(size(3000));
      expect(graph.links.map((link) => link.source + '>' + link.target).sort()).toEqual([
        'app:backend/api.py>app:backend/api_helpers.py', 'app:backend/api.py>app:backend/importer.py',
        'app:backend/importer.py>app:backend/api.py', 'app:static/js/ui.js>app:backend/api.py'
      ]);
    });

    test('Modules and Files share one layout of module circles; Functions has its own, and one for a module alone', () => {
      const context = window.QualityDashboard.createContext({ code_map: codeMap(), report: report() }, {});
      const view = window.QualityMap.mapView;
      const files = view(context, 'files', null);
      expect(view(context, 'modules', 'app.api')).toBe(files);
      expect(files.regions.map((region) => region.id).sort()).toEqual(['app.api', 'app.import', 'app.ui', 'engine.core']);
      expect(files.regions.find((region) => region.id === 'app.api')).toMatchObject({ of: 'module', label: 'api', count: 2 });
      const at = Object.fromEntries(files.regions.map((region) => [region.id, region]));
      expect(at['app.import'].y).toBeLessThan(at['app.api'].y);
      expect(at['engine.core'].x).toBeGreaterThan(at['app.api'].x);
      for (let a = 0; a < files.regions.length; a++) {
        for (let b = a + 1; b < files.regions.length; b++) {
          expect(Math.hypot(files.regions[a].x - files.regions[b].x, files.regions[a].y - files.regions[b].y)).toBeGreaterThan(files.regions[a].r + files.regions[b].r);
        }
      }
      const all = view(context, 'symbols', null);
      expect(all).not.toBe(files);
      expect(view(context, 'symbols', null)).toBe(all);
      expect(all.regions.map((region) => region.id).sort()).toEqual(['app.api', 'app.import']);
      const alone = view(context, 'symbols', 'app.api');
      expect(alone.regions.map((region) => region.label).sort()).toEqual(['api.py', 'api_helpers.py']);
      expect(alone.regions[0].of).toBe('file');
    });

    test('on Files a line that would run through a third module goes around it', () => {
      // Three modules in a chain, so the line from the top one to the bottom one would cross the middle one.
      const map = codeMap();
      map.modules = ['top', 'middle', 'bottom'].map((name, index, names) => Object.assign({}, map.modules[0], {
        id: 'app.' + name, dependencies: names.slice(index + 1).map((other) => 'app.' + other), entrypoints: []
      }));
      map.files = ['top', 'middle', 'bottom'].map((name) => ({ id: 'app:' + name + '.py', module: 'app.' + name, lines: 300, symbols: 1 }));
      map.links = [
        { source: 'app:top.py', target: 'app:bottom.py', kind: 'imports', count: 1 },
        { source: 'app:bottom.py', target: 'app:top.py', kind: 'uses', count: 1 },
        { source: 'app:top.py', target: 'app:middle.py', kind: 'imports', count: 1 }
      ];
      Object.assign(map, { contracts: [], symbols: [], symbol_links: [], clones: [], interface: {} });
      const context = window.QualityDashboard.createContext({ code_map: map, report: null }, {});
      const edges = Object.fromEntries(window.QualityRendering.mapElements(context, { level: 'files', colorBy: 'module' }, window.QualityMap.mapView(context, 'files'))
        .filter((item) => item.group === 'edges').map((item) => [item.data.id, item]));
      // Down the outer side of the column, as the dependency between the two modules does on Modules; back up the inner side.
      expect(edges['dot-link:app:top.py>app:bottom.py'].classes).toBe('dot-link crossing around');
      expect(edges['dot-link:app:top.py>app:bottom.py'].data.arc).toBeGreaterThan(0);
      expect(edges['dot-link:app:bottom.py>app:top.py'].data.arc).toBe(edges['dot-link:app:top.py>app:bottom.py'].data.arc);
      // Neighbours have nothing between them: their line stays straight.
      expect(edges['dot-link:app:top.py>app:middle.py']).toMatchObject({ classes: 'dot-link crossing', data: { arc: 0 } });
    });

    test('the map cannot be dragged out of view: a small map stays whole on the stage, a large one keeps covering it', () => {
      const within = window.QualityMap.panWithin;
      const bounds = { x1: 0, y1: 0, x2: 200, y2: 100 };
      // Smaller than an 800 by 600 stage: it stays 50 pixels inside each edge.
      expect(within({ x: -500, y: 900 }, 1, bounds, 800, 600, 50)).toEqual({ x: 50, y: 450 });
      expect(within({ x: 300, y: 200 }, 1, bounds, 800, 600, 50)).toEqual({ x: 300, y: 200 });
      // Ten times larger than the stage: its edges come no further in than 50 pixels.
      expect(within({ x: 400, y: -5000 }, 10, bounds, 800, 600, 50)).toEqual({ x: 50, y: -450 });
      expect(within({ x: -700, y: -200 }, 10, bounds, 800, 600, 50)).toEqual({ x: -700, y: -200 });
    });

    test('each level draws circles, dots and lines: arcs between modules, a dashed line for a copy, hollow and ringed dots', () => {
      const context = window.QualityDashboard.createContext({ code_map: codeMap(), report: report() }, {});
      const draw = (level, moduleId) => window.QualityRendering.mapElements(context, { level, module: moduleId, colorBy: 'module' },
        window.QualityMap.mapView(context, level, moduleId));
      const byId = (elements) => Object.fromEntries(elements.map((item) => [item.data.id, item]));
      const modules = byId(draw('modules', null));
      expect(modules['app.api']).toMatchObject({ classes: 'module', data: { kind: 'module', color: '#eb6834' } });
      expect(modules['app.api'].data.size).toBeGreaterThan(modules['app.ui'].data.size);
      expect(modules['region-label:app.api'].data.label).toBe('api');
      expect(modules['link:app.import>app.api']).toMatchObject({ classes: 'module-link declared', data: { label: '5' } });
      expect(modules['link:app.api>app.import'].classes).toBe('module-link undeclared');
      expect(modules['link:app.import>app.ui']).toMatchObject({ classes: 'module-link unused', data: { label: '' } });
      // Both bend to the right of their direction: the one that follows the layering outwards, the other inwards.
      expect(modules['link:app.import>app.api'].data.arc).toBeGreaterThan(0);
      expect(modules['link:app.api>app.import'].data.arc).toBe(modules['link:app.import>app.api'].data.arc);
      expect(modules['contract:bundle'].classes).toBe('contract');
      expect(modules['contract:bundle~engine.core'].classes).toBe('contract-link');
      const files = byId(draw('files', null));
      expect(files['region:app.api']).toMatchObject({ classes: 'region', data: { of: 'module', count: 2 } });
      expect(files['app:backend/api.py']).toMatchObject({ classes: 'dot', data: { kind: 'file', module: 'app.api', label: 'api.py' } });
      expect(files['engine:src/core.py'].classes).toBe('dot large');
      expect(files['dot-link:app:static/js/ui.js>app:backend/api.py'].classes).toBe('dot-link crossing undeclared');
      expect(files['dot-link:app:backend/api.py>app:backend/api_helpers.py'].classes).toBe('dot-link internal');
      expect(files['clone:0']).toMatchObject({ classes: 'clone', data: { source: 'app:backend/api.py', target: 'app:backend/importer.py', kind: 'clone', clone: 0 } });
      expect(files['dot-link:app:backend/importer.py>app:backend/api.py'].data.arc).toBe(0);
      const functions = byId(draw('symbols', null));
      expect(functions['app:backend/importer.py:run@5'].classes).toBe('dot unused');
      expect(functions['app:backend/api.py:serve@3']).toMatchObject({ classes: 'dot', data: { kind: 'symbol', file: 'app:backend/api.py' } });
      expect(functions['clone:0']).toBeUndefined();
    });

    test('search ranks the exact name, then a prefix, then a part of the name, then the path', () => {
      const map = codeMap();
      const symbols = window.QualityMap.symbolGraph(map).nodes;
      const match = (query, limit) => window.QualityMap.matchNames(symbols, map.files, query, limit);
      expect(match('  ')).toEqual([]);
      expect(match('serve')[0]).toEqual({ kind: 'symbol', id: 'app:backend/api.py:serve@3', name: 'serve', detail: 'backend/api.py:3' });
      expect(match('help').map((row) => row.kind + ' ' + row.name)).toEqual(['symbol helper', 'file api_helpers.py', 'symbol fmt']);
      // Longer files come first among equal matches; case does not matter. A file without functions is found too.
      expect(match('API').slice(0, 2).map((row) => row.id)).toEqual(['app:backend/api.py', 'app:backend/api_helpers.py']);
      expect(match('API')[0].detail).toBe('backend/api.py · 400 lines');
      expect(match('ui.js')[0]).toMatchObject({ kind: 'file', id: 'app:static/js/ui.js' });
      expect(match('a', 2)).toHaveLength(2);
      expect(match('nothing-like-this')).toEqual([]);
    });

    test('names show from the largest dot down, never over another name, and a selection is always named', () => {
      const node = (id, users, name) => ({ id, name: name || id, size: window.QualityMap.symbolSize(users) });
      const map = {
        graph: { nodes: [node('big', 25, 'big_name'), node('near', 9, 'near_name'), node('far', 9), node('small', 0)] },
        positions: { big: { x: 0, y: 0 }, near: { x: 0, y: -40 }, far: { x: 500, y: 0 }, small: { x: 900, y: 0 } }
      };
      const measure = (label, size) => label.length * size * 0.6;
      const places = window.QualityMap.labelPlaces;
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

    test('region names come first, 12 pixels tall on top of their circle, and dot names go around them', () => {
      const node = (id, users, name) => ({ id, name: name || id, size: window.QualityMap.symbolSize(users) });
      const measure = (label, size) => label.length * size * 0.6;
      const places = window.QualityMap.labelPlaces;
      const map = {
        graph: { nodes: [node('big', 25, 'big_name')] },
        positions: { big: { x: 0, y: -100 } },
        // The big dot's name sits right where the first region's name goes; the second region's name would cover the first's.
        regions: [{ id: 'a', label: 'files.py', x: 0, y: 0, r: 80 }, { id: 'b', label: 'other.py', x: 5, y: 2, r: 80 }, { id: 'c', label: 'far.py', x: 500, y: 0, r: 40 }]
      };
      const kept = places(map, 1, { measure });
      expect(kept.map((row) => row.id)).toEqual(['region-label:a', 'region-label:c', 'big']);
      expect(kept[0].font).toBe(12);
      expect((kept[0].y1 + kept[0].y2) / 2).toBe(-80);
      // The dot's name, below it, would cover region a's name, so it goes above the dot.
      expect(kept[2].above).toBe(true);
      expect(places(map, 2, { measure })[0].font).toBe(6);
    });
  });

  describe('page', () => {
    function pageHtml() {
      return `
        <div id="qualityDashboard" data-api-url="/api/quality">
          <div id="qualityUnavailable" hidden><p id="qualityUnavailableText"></p></div>
          <div id="qualityContent" hidden>
            <span id="qualityRunEyebrow"></span><h2 id="qualityRunTitle"></h2><p id="qualityWarning" hidden></p><span id="qualityRunStatus"></span>
            <dl id="qualitySummary"></dl>
            <div id="qualityFigures"></div>
            <section id="qualityMapSection">
              <div class="quality-workspace">
                <button data-level="modules"></button><button data-level="files"></button><button data-level="symbols"></button>
                <div id="qualityColorBy"><button data-color-by="module"></button><button data-color-by="criticality"></button><button data-color-by="coverage"></button></div>
                <button id="qualityPanelToggle" aria-pressed="true"></button>
                <button id="qualityFullscreen" aria-pressed="false"><i class="fas fa-expand"></i><span class="quality-tool__text">Expand</span></button>
                <aside id="qualityExplorer">
                  <input type="search" id="qualitySearch"><ul id="qualitySearchResults" hidden></ul>
                  <input type="checkbox" id="qualityEdgesToggle" checked><input type="checkbox" id="qualityLabelsToggle" checked>
                  <span id="qualityExplorerUnit"></span><button id="qualityExplorerReset" data-reset></button><ul id="qualityExplorerModules"></ul>
                </aside>
                <div class="quality-map-stage">
                  <div id="qualityMap"></div><span id="qualityBreadcrumb"></span><div id="qualityTooltip" hidden></div><div id="qualityZoomHint"></div>
                  <button id="qualityFit"></button>
                </div>
                <aside id="qualityPanel"></aside>
                <ul id="qualityLegend"></ul>
              </div>
            </section>
            <div id="qualityCleanup"></div>
            <div id="qualityFindings"></div>
            <div id="qualityBlindSpots"></div>
            <section data-needs-report><table id="qualityTable"></table></section>
            <section data-needs-report><div id="qualityChecks"></div></section>
          </div>
        </div>`;
    }

    function respond(data) {
      global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(data) }));
    }

    const results = (extra) => Object.assign({
      available: true, revision: 'a'.repeat(40), source: 'ci', run_url: 'https://ci/run',
      source_urls: { app: 'https://github.com/x/app/blob/sha/' }, report: report(), code_map: codeMap()
    }, extra);

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
          boundingBox: () => ({ x1: 0, y1: 0, x2: 400, y2: 300 }),
          addClass: (names) => each((item) => names.split(' ').forEach((name) => item.classes.add(name))),
          removeClass: (names) => each((item) => names.split(' ').forEach((name) => item.classes.delete(name))),
          toggleClass: (name, on) => each((item) => (on ? item.classes.add(name) : item.classes.delete(name))),
          select: () => each((item) => { item.selected = true; }),
          unselect: () => each((item) => { item.selected = false; }),
          remove: () => { items = items.filter((item) => !list.includes(item)); },
          nodes: () => collection(list.filter((item) => item.isNode())),
          edges: () => collection(list.filter((item) => !item.isNode())),
          union: (other) => collection(Array.from(new Set(list.concat(other.list)))),
          not: (other) => collection(list.filter((item) => (typeof other === 'string' ? !matches(item, other) || !/\./.test(other) : !ids(other).has(item.id())))),
          renderedBoundingBox: () => ({ x1: 0, x2: 10, y1: 0, y2: 10 }),
          connectedNodes: () => collection(items.filter((item) => item.isNode() && list.some((edge) => [edge.data('source'), edge.data('target')].includes(item.id())))),
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
        on: jest.fn(), fit: jest.fn(), resize: jest.fn(), center: jest.fn(), animate: jest.fn(), width: () => 800, height: () => 600, pan: jest.fn(() => ({ x: 5000, y: 100 })),
        zoom: jest.fn(() => 1), batch: (fn) => fn(), layout: jest.fn(() => ({ run: jest.fn() }))
      };
      window.cytoscape = jest.fn(() => instance);
      return instance;
    }

    const nextFrame = () => new Promise((resolve) => window.requestAnimationFrame(resolve));
    const click = (selector) => document.querySelector(selector).dispatchEvent(new MouseEvent('click', { bubbles: true }));

    let getContext;
    beforeEach(() => {
      document.body.innerHTML = pageHtml();
      // JSDOM has no canvas: label widths fall back to an estimate. It cannot scroll either.
      getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = () => null;
      Element.prototype.scrollIntoView = jest.fn();
    });

    afterEach(() => {
      HTMLCanvasElement.prototype.getContext = getContext;
      delete Element.prototype.scrollIntoView;
      delete global.fetch;
      delete window.cytoscape;
    });

    async function open(level, data) {
      const cy = graphCytoscape();
      respond(data || results());
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      if (level) {
        click('[data-level="' + level + '"]');
        await nextFrame();
      }
      return cy;
    }
    const handler = (cy, event, selector) => cy.on.mock.calls.find((call) => call[0] === event && (selector === undefined ? typeof call[1] === 'function' : call[1] === selector)).slice(-1)[0];
    const searchFor = (text) => {
      const search = document.getElementById('qualitySearch');
      search.value = text;
      search.dispatchEvent(new Event('input'));
      search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    };
    const escape = () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    const pressed = (selector) => document.querySelector(selector).getAttribute('aria-pressed');
    const panel = () => document.getElementById('qualityPanel').textContent;

    test('shows the CI results of the running commit, the findings, the cleanup candidates and the module circles', async () => {
      const cy = await open();
      expect(document.getElementById('qualityContent').hidden).toBe(false);
      expect(document.getElementById('qualityRunTitle').textContent).toBe('CI results for commit aaaaaaa');
      expect(document.getElementById('qualityWarning').hidden).toBe(true);
      expect(document.getElementById('qualityRunStatus').textContent).toBe('Checks failed');
      expect(document.getElementById('qualitySummary').textContent).toContain('1 of 2 passed');
      expect(document.querySelector('#qualitySummary a[href="https://github.com/x/app/commit/' + 'a'.repeat(40) + '"]')).not.toBeNull();
      expect(document.querySelector('#qualitySummary a[href="https://ci/run"]')).not.toBeNull();
      expect(document.getElementById('qualityFigures').textContent).toContain('Functions nothing mentions');
      expect(document.getElementById('qualityFindings').textContent).toContain('_private');
      const tidy = document.getElementById('qualityCleanup').textContent;
      expect(tidy).toContain('run');
      expect(tidy).toContain('api.py ⇄ importer.py');
      expect(tidy).toContain('1,200 lines');
      const spots = document.getElementById('qualityBlindSpots').textContent;
      expect(spots).toContain('/api/missing');
      expect(spots).toContain('/api/old');
      expect(spots).toContain('config.url');
      expect(spots).toContain('Static reading only.');
      expect(document.querySelectorAll('#qualityTable tbody tr')).toHaveLength(2);
      expect(document.querySelectorAll('#qualityTable thead th')).toHaveLength(7);
      expect(document.getElementById('qualityTable').textContent).toContain('87.5%');
      expect(document.querySelector('#qualityTable .quality-meter span').style.width).toBe('87.5%');
      expect(panel()).toContain('How to read the modules');
      expect(cy.layout).toHaveBeenCalledWith(expect.objectContaining({ name: 'preset', fit: true }));
      expect(cy.nodes('.module').length).toBe(4);
      expect(cy.getElementById('link:app.api>app.import').hasClass('undeclared')).toBe(true);
      expect(cy.getElementById('link:app.import>app.ui').hasClass('unused')).toBe(true);
      expect(cy.getElementById('region-label:app.api').hasClass('labelled')).toBe(true);
      expect(pressed('[data-level="modules"]')).toBe('true');
      expect(pressed('[data-color-by="module"]')).toBe('true');
      // The list counts lines on this level, in the order of the map, and is the colour key.
      expect(document.getElementById('qualityExplorerUnit').textContent).toBe('lines');
      expect(Array.from(document.querySelectorAll('[data-explorer-module]')).map((button) => button.textContent)).toEqual(['import900', 'api500', 'ui50', 'core1,200']);
      // A thin line parts the repositories.
      expect(document.querySelector('.quality-explorer__repository [data-explorer-module]').dataset.explorerModule).toBe('engine.core');
      expect(document.querySelectorAll('.quality-explorer__repository').length).toBe(1);
      expect(document.getElementById('qualityLegend').textContent).toContain('Circle size: lines of code');
    });

    test('a local run says so, and a map without a report hides the result tables', async () => {
      await open(null, results({ source: 'local', revision: null, run_url: null, report: null }));
      expect(document.getElementById('qualityRunEyebrow').textContent).toBe('Measured on this computer');
      expect(document.getElementById('qualityRunTitle').textContent).toBe('Local run');
      expect(document.getElementById('qualityWarning').hidden).toBe(false);
      expect(document.getElementById('qualityRunStatus').textContent).toBe('Map only');
      expect(document.getElementById('qualitySummary').textContent).toBe('');
      document.querySelectorAll('[data-needs-report]').forEach((section) => expect(section.hidden).toBe(true));
      expect(document.getElementById('qualityCleanup').textContent).toContain('run');
    });

    test('missing results say why, and are never shown as content', async () => {
      const text = () => document.getElementById('qualityUnavailableText').textContent;
      respond({ available: false, revision: 'c'.repeat(40), reason: 'no_results' });
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      expect(document.getElementById('qualityUnavailable').hidden).toBe(false);
      expect(text()).toContain('No CI results for commit ccccccc yet');
      document.body.innerHTML = pageHtml();
      respond({ available: false, revision: null, reason: 'unknown_commit' });
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      expect(text()).toContain('does not know which commit it runs');
      document.body.innerHTML = pageHtml();
      global.fetch = jest.fn(() => Promise.reject(new Error('offline')));
      await window.QualityDashboard.init(document.getElementById('qualityDashboard'));
      expect(document.getElementById('qualityUnavailable').hidden).toBe(false);
      expect(text()).toContain('could not be loaded');
      expect(document.getElementById('qualityContent').hidden).toBe(true);
    });

    test('Files draws every file in its module\'s circle, with the copies, and its own guide and counts', async () => {
      const cy = await open('files');
      expect(cy.nodes('.dot').length).toBe(5);
      expect(cy.nodes('.region').map((node) => node.id()).sort()).toEqual(['region:app.api', 'region:app.import', 'region:app.ui', 'region:engine.core']);
      expect(cy.edges('.dot-link').length).toBe(4);
      expect(cy.edges('.clone').length).toBe(1);
      expect(cy.nodes('.dot.large').map((node) => node.id())).toEqual(['engine:src/core.py']);
      expect(pressed('[data-level="files"]')).toBe('true');
      expect(panel()).toContain('How to read the files');
      expect(document.getElementById('qualityBreadcrumb').textContent).toContain('All files');
      expect(document.getElementById('qualityExplorerUnit').textContent).toBe('files');
      expect(document.getElementById('qualityLegend').textContent).toContain('Copied code');
      // Colouring by coverage paints each file with its own.
      click('[data-color-by="coverage"]');
      expect(cy.getElementById('app:backend/api.py').data('color')).toBe('#174092');
      expect(cy.getElementById('app:static/js/ui.js').data('color')).toBe('#e9ecef');
      expect(pressed('[data-color-by="coverage"]')).toBe('true');
      // A file's panel has its coverage, its copies and the way to its functions.
      handler(cy, 'tap')({ target: cy.getElementById('app:backend/api.py') });
      expect(panel()).toContain('90% branch coverage');
      expect(panel()).toContain('Lines 30–43');
      expect(panel()).toContain('Its functions');
      // The copy itself can be selected.
      handler(cy, 'tap')({ target: cy.getElementById('clone:0') });
      expect(panel()).toContain('14 lines found twice');
    });

    test('Functions draws every function coloured by module, hollow when nothing mentions it, with the switches', async () => {
      const cy = await open('symbols');
      expect(cy.nodes('.dot').length).toBe(4);
      expect(cy.edges('.dot-link').length).toBe(3);
      expect(cy.nodes('.dot.unused').map((node) => node.id())).toEqual(['app:backend/importer.py:run@5']);
      expect(cy.getElementById('app:backend/api.py:serve@3').data('color')).toBe('#eb6834');
      expect(Array.from(document.querySelectorAll('[data-explorer-module]')).map((button) => button.textContent)).toEqual(['import1', 'api3', 'ui0', 'core0']);
      expect(panel()).toContain('How to read the functions');
      expect(document.getElementById('qualityLegend').textContent).toContain('Nothing mentions it');
      expect(document.getElementById('qualityBreadcrumb').textContent).toContain('All functions');

      document.getElementById('qualityEdgesToggle').checked = false;
      document.getElementById('qualityEdgesToggle').dispatchEvent(new Event('change'));
      expect(cy.edges('.dot-link.hidden').length).toBe(3);
      document.getElementById('qualityLabelsToggle').checked = false;
      document.getElementById('qualityLabelsToggle').dispatchEvent(new Event('change'));
      expect(cy.nodes('.dot.unlabelled').length).toBe(4);

      click('[data-color-by="criticality"]');
      expect(cy.getElementById('app:backend/api.py:serve@3').data('color')).toBe('#617db5');
      // The colour encoding stays when the level changes.
      click('[data-level="modules"]');
      await nextFrame();
      expect(cy.getElementById('app.api').data('color')).toBe('#617db5');
      expect(pressed('[data-color-by="criticality"]')).toBe('true');
    });

    test('the module in focus is selected on Modules, lit on Files, drawn alone on Functions, and survives the change of level', async () => {
      const cy = await open();
      click('[data-explorer-module="app.api"]');
      expect(pressed('[data-explorer-module="app.api"]')).toBe('true');
      expect(cy.$(':selected').id()).toBe('app.api');
      // Only the module itself stays: the modules at the other end of its lines fade as every other does.
      expect(cy.nodes('.module.faded').map((node) => node.id()).sort()).toEqual(['app.import', 'app.ui', 'engine.core']);
      expect(cy.getElementById('link:app.import>app.api').hasClass('lit')).toBe(true);
      expect(panel()).toContain('Serve data.');
      expect(panel()).toContain('To clean up');
      expect(document.getElementById('qualityBreadcrumb').textContent).toMatch(/All modules.*api/);

      cy.fit.mockClear();
      click('[data-level="files"]');
      await nextFrame();
      expect(pressed('[data-explorer-module="app.api"]')).toBe('true');
      // Its circle fills the map; its files stay lit and the lines stay faint.
      expect(cy.fit.mock.calls[0][0].id()).toBe('region:app.api');
      expect(cy.nodes('.dot.faded').map((node) => node.id()).sort()).toEqual(['app:backend/importer.py', 'app:static/js/ui.js', 'engine:src/core.py']);
      // The lines that leave the module are lit and the ones inside it stay faint.
      expect(cy.edges('.lit').map((edge) => edge.id()).sort()).toEqual(['clone:0', 'dot-link:app:backend/api.py>app:backend/importer.py',
        'dot-link:app:backend/importer.py>app:backend/api.py', 'dot-link:app:static/js/ui.js>app:backend/api.py']);
      expect(cy.getElementById('dot-link:app:backend/api.py>app:backend/api_helpers.py').hasClass('lit')).toBe(false);
      expect(panel()).toContain('Serve data.');
      // Dragging further than the map reaches is pulled back.
      cy.on.mock.calls.filter((call) => call[0] === 'viewport').forEach((call) => call[1]());
      expect(cy.pan).toHaveBeenLastCalledWith({ x: 320, y: 100 });
      // Selecting one of its files lights that file's lines; clearing it comes back to the module.
      handler(cy, 'tap')({ target: cy.getElementById('app:backend/api_helpers.py') });
      expect(cy.edges('.lit').map((edge) => edge.id())).toEqual(['dot-link:app:backend/api.py>app:backend/api_helpers.py']);
      escape();
      expect(cy.$(':selected').length).toBe(0);
      expect(panel()).toContain('Serve data.');

      click('[data-level="symbols"]');
      await nextFrame();
      expect(cy.nodes('.dot').map((node) => node.id()).sort()).toEqual(['app:backend/api.py:helper@10', 'app:backend/api.py:serve@3', 'app:backend/api_helpers.py:fmt@2']);
      expect(cy.nodes('.region').map((node) => node.id()).sort()).toEqual(['region:app:backend/api.py', 'region:app:backend/api_helpers.py']);
      expect(document.getElementById('qualityLegend').textContent).toContain('Circle: a file');
      expect(document.getElementById('qualityBreadcrumb').textContent).toMatch(/All functions.*api/);
      // The breadcrumb, Reset, the module itself and Esc each give up the focus.
      click('#qualityBreadcrumb [data-reset]');
      expect(cy.nodes('.dot').length).toBe(4);
      click('[data-explorer-module="app.import"]');
      expect(cy.nodes('.dot').length).toBe(1);
      click('#qualityExplorerReset');
      expect(cy.nodes('.dot').length).toBe(4);
      click('[data-explorer-module="app.import"]');
      click('[data-explorer-module="app.import"]');
      expect(cy.nodes('.dot').length).toBe(4);
      click('[data-explorer-module="app.import"]');
      escape();
      expect(cy.nodes('.dot').length).toBe(4);
      expect(panel()).toContain('How to read the functions');
    });

    test('the box before a module adds it to the modules in focus, which keep only the lines between them', async () => {
      const cy = await open();
      const picked = () => Array.from(document.querySelectorAll('[data-explorer-pick][aria-checked="true"]')).map((box) => box.dataset.explorerPick);
      click('[data-explorer-pick="app.api"]');
      // One module picked is the module in focus, as with a click on its name.
      expect(cy.$(':selected').id()).toBe('app.api');
      click('[data-explorer-pick="app.import"]');
      expect(picked().sort()).toEqual(['app.api', 'app.import']);
      expect(pressed('[data-explorer-module="app.import"]')).toBe('true');
      expect(cy.nodes('.module.faded').map((node) => node.id()).sort()).toEqual(['app.ui', 'engine.core']);
      expect(cy.edges('.lit').map((edge) => edge.id()).sort()).toEqual(['link:app.api>app.import', 'link:app.import>app.api']);
      expect(panel()).toContain('2 modules');
      expect(panel()).toContain('Dependencies between them (2)');
      expect(document.getElementById('qualityBreadcrumb').textContent).toMatch(/All modules.*api \+ import/);

      // On Files both circles are fitted, and only the lines from one module to the other are lit.
      cy.fit.mockClear();
      click('[data-level="files"]');
      await nextFrame();
      expect(picked().sort()).toEqual(['app.api', 'app.import']);
      expect(cy.fit.mock.calls[0][0].map((node) => node.id()).sort()).toEqual(['region:app.api', 'region:app.import']);
      expect(cy.nodes('.dot.faded').map((node) => node.id()).sort()).toEqual(['app:static/js/ui.js', 'engine:src/core.py']);
      // Copied code between the two counts as a connection as well.
      expect(cy.edges('.lit').map((edge) => edge.id()).sort()).toEqual(['clone:0', 'dot-link:app:backend/api.py>app:backend/importer.py', 'dot-link:app:backend/importer.py>app:backend/api.py']);
      // Every other line is not drawn at all.
      expect(cy.edges('.out').map((edge) => edge.id()).sort()).toEqual(['dot-link:app:backend/api.py>app:backend/api_helpers.py', 'dot-link:app:static/js/ui.js>app:backend/api.py']);

      // On Functions several modules stay among every function; one alone is drawn alone.
      click('[data-level="symbols"]');
      await nextFrame();
      expect(cy.nodes('.dot').length).toBe(4);
      click('[data-explorer-pick="app.import"]');
      await nextFrame();
      expect(picked()).toEqual(['app.api']);
      expect(cy.nodes('.dot').length).toBe(3);
      // A click on a name with Ctrl adds it; a plain click keeps that module only; Esc gives up several at once.
      document.querySelector('[data-explorer-module="app.import"]').dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: true }));
      await nextFrame();
      expect(picked().sort()).toEqual(['app.api', 'app.import']);
      escape();
      expect(picked()).toEqual([]);
      expect(document.getElementById('qualityExplorerReset').disabled).toBe(true);
    });

    test('a double-click goes one level in; a click on a circle of dots is a click on the background', async () => {
      const cy = await open();
      handler(cy, 'dbltap', 'node.module')({ target: cy.getElementById('app.api') });
      await nextFrame();
      expect(pressed('[data-level="files"]')).toBe('true');
      expect(pressed('[data-explorer-module="app.api"]')).toBe('true');
      // A click inside a circle clears the selection, then the focus.
      handler(cy, 'tap')({ target: cy.getElementById('app:backend/api.py') });
      expect(cy.$(':selected').length).toBe(1);
      handler(cy, 'tap')({ target: cy.getElementById('region:app.api') });
      expect(cy.$(':selected').length).toBe(0);
      expect(pressed('[data-explorer-module="app.api"]')).toBe('true');
      handler(cy, 'tap')({ target: cy.getElementById('region:app.api') });
      expect(pressed('[data-explorer-module="app.api"]')).toBe('false');
      // A file's double-click draws its module's functions, with the file's own selected.
      handler(cy, 'dbltap', 'node.dot')({ target: cy.getElementById('app:backend/api.py') });
      await nextFrame();
      expect(pressed('[data-level="symbols"]')).toBe('true');
      expect(pressed('[data-explorer-module="app.api"]')).toBe('true');
      expect(cy.$(':selected').map((node) => node.id()).sort()).toEqual(['app:backend/api.py:helper@10', 'app:backend/api.py:serve@3']);
      expect(panel()).toContain('api.py');
      // On Functions a module's circle draws it alone, and a click on the background leaves it drawn.
      click('#qualityExplorerReset');
      handler(cy, 'dbltap', 'node.region')({ target: cy.getElementById('region:app.import') });
      expect(cy.nodes('.dot').length).toBe(1);
      handler(cy, 'tap')({ target: cy });
      expect(cy.nodes('.dot').length).toBe(1);
      // A module's circle on Files goes to its functions.
      click('[data-level="files"]');
      await nextFrame();
      handler(cy, 'dbltap', 'node.region')({ target: cy.getElementById('region:app.api') });
      await nextFrame();
      expect(pressed('[data-level="symbols"]')).toBe('true');
      expect(cy.nodes('.dot').length).toBe(3);
    });

    test('search opens a function on Functions and a file on Files, and Esc steps back', async () => {
      const cy = await open();
      const search = document.getElementById('qualitySearch');
      search.value = 'serv';
      search.dispatchEvent(new Event('input'));
      const list = document.getElementById('qualitySearchResults');
      expect(list.hidden).toBe(false);
      expect(list.querySelector('[role="option"]').textContent).toContain('serve');
      expect(search.getAttribute('aria-activedescendant')).toBe('qualitySearchOption0');
      search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
      await nextFrame();
      expect(list.hidden).toBe(true);
      expect(pressed('[data-level="symbols"]')).toBe('true');
      expect(cy.$(':selected').id()).toBe('app:backend/api.py:serve@3');
      expect(cy.animate).toHaveBeenCalled();
      expect(panel()).toContain('run');
      expect(cy.nodes('.dot.named').length).toBeGreaterThan(0);
      // While one module is drawn, a match in another module draws that one.
      searchFor('run');
      expect(pressed('[data-explorer-module="app.import"]')).toBe('true');
      expect(cy.$(':selected').id()).toBe('app:backend/importer.py:run@5');
      expect(panel()).toContain('probably unused');
      // The first Esc empties the box, the next clears the selection, the next the module.
      search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
      expect(search.value).toBe('');
      expect(cy.$(':selected').length).toBe(1);
      escape();
      expect(cy.$(':selected').length).toBe(0);
      expect(cy.nodes('.dot').length).toBe(1);
      escape();
      expect(cy.nodes('.dot').length).toBe(4);
      // A file is found by name and selected among the files.
      search.value = 'api_helpers';
      search.dispatchEvent(new Event('input'));
      click('#qualitySearchOption0');
      await nextFrame();
      expect(pressed('[data-level="files"]')).toBe('true');
      expect(cy.$(':selected').id()).toBe('app:backend/api_helpers.py');
      expect(panel()).toContain('40% of lines covered');
    });

    test('a row of the page opens its place on the map', async () => {
      const cy = await open('symbols');
      click('#qualityCleanup [data-select-clone="0"]');
      await nextFrame();
      expect(pressed('[data-level="files"]')).toBe('true');
      expect(cy.$(':selected').id()).toBe('clone:0');
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
      click('#qualityCleanup [data-select-function]');
      await nextFrame();
      expect(pressed('[data-level="symbols"]')).toBe('true');
      expect(cy.$(':selected').id()).toBe('app:backend/importer.py:run@5');
      click('#qualityFindings [data-select-link="app.api>app.import"]');
      await nextFrame();
      expect(pressed('[data-level="modules"]')).toBe('true');
      expect(cy.$(':selected').id()).toBe('link:app.api>app.import');
      expect(panel()).toContain('does not declare this dependency');
      click('#qualityTable [data-select-module="app.import"]');
      expect(cy.$(':selected').id()).toBe('app.import');
      // A module named in the panel takes the focus on the level shown.
      click('#qualityPanel [data-go-level="symbols"]');
      await nextFrame();
      expect(cy.nodes('.dot').length).toBe(1);
      click('#qualityPanel [data-select-module="app.api"]');
      expect(cy.nodes('.dot').length).toBe(3);
    });

    test('the details panel hides to widen the map and opens again on a selection', async () => {
      const cy = await open('symbols');
      const workspace = document.querySelector('.quality-workspace');
      const toggle = document.getElementById('qualityPanelToggle');
      cy.resize.mockClear();
      click('#qualityPanelToggle');
      expect(workspace.classList.contains('is-panel-hidden')).toBe(true);
      expect(toggle.getAttribute('aria-pressed')).toBe('false');
      expect(toggle.title).toBe('Show the details panel');
      expect(cy.resize).toHaveBeenCalledTimes(1);
      searchFor('serv');
      expect(workspace.classList.contains('is-panel-hidden')).toBe(false);
      expect(toggle.getAttribute('aria-pressed')).toBe('true');
      expect(panel()).toContain('serve');
    });

    test('the guide, and a module drawn alone, hide the panel back into the Details button', async () => {
      const cy = await open('symbols');
      const workspace = document.querySelector('.quality-workspace');
      const toggle = document.getElementById('qualityPanelToggle');
      click('#qualityPanel [data-hide-panel]');
      expect(workspace.classList.contains('is-panel-hidden')).toBe(true);
      expect(toggle.classList.contains('is-nudged')).toBe(true);
      expect(document.activeElement).toBe(toggle);
      click('#qualityPanelToggle');
      expect(workspace.classList.contains('is-panel-hidden')).toBe(false);
      expect(toggle.classList.contains('is-nudged')).toBe(false);
      expect(document.getElementById('qualityPanel').classList.contains('is-opening')).toBe(true);
      click('[data-explorer-module="app.api"]');
      click('#qualityPanel [data-hide-panel]');
      expect(workspace.classList.contains('is-panel-hidden')).toBe(true);
      expect(cy.nodes('.dot').length).toBe(3);
    });

    test('the expand button fills the window below the navbar and Esc returns to the page', async () => {
      const cy = await open();
      const workspace = document.querySelector('.quality-workspace');
      const button = document.getElementById('qualityFullscreen');
      cy.fit.mockClear();
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
      escape();
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
  });
});
