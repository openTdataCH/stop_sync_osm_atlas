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
      { source: 'app:backend/api.py', target: 'app:backend/api_helpers.py', kind: 'imports', count: 1 }
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

  test('findings report undeclared links, cycles, private names and unused declarations', () => {
    const map = codeMap();
    const findings = window.QualityDashboard.boundaryFindings(map, window.QualityDashboard.aggregateModuleLinks(map));
    expect(findings.undeclared.map((link) => link.source + '>' + link.target)).toEqual(['app.api>app.import']);
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
    expect(graph.files.map((file) => file.id)).toEqual(['app:backend/api.py', 'app:backend/api_helpers.py', 'app:backend/importer.py']);
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
    expect(color(module, report(), 'criticality')).toBe('#1c5cab');
    expect(color(module, report(), 'coverage')).toBe('#104281');
    expect(color(module, { modules: {} }, 'coverage')).toBe('#d5d8dd');
    expect(color(module, report(), 'repository')).toBe('#2a78d6');
  });

  test('escapes catalog text before it reaches the page', () => {
    expect(window.QualityDashboard.escapeHtml('<b title="x">&</b>')).toBe('&lt;b title=&quot;x&quot;&gt;&amp;&lt;/b&gt;');
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
              <span id="qualityBreadcrumb"></span>
              <button data-view-toggle="modules"></button><button data-view-toggle="files"></button>
              <select id="qualityColorBy"><option value="criticality">c</option><option value="coverage">b</option></select>
              <input type="checkbox" id="qualityUnusedToggle" checked>
              <button id="qualityFit"></button>
              <div id="qualityMap"></div><div id="qualityTooltip" hidden></div>
              <aside id="qualityPanel"></aside>
              <ul id="qualityLegend"></ul>
            </section>
            <section id="qualityFindingsSection"><div id="qualityFindings"></div></section>
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
