const fs = require('fs');
const path = require('path');

describe('ProblemsUI route contradiction rendering', () => {
  beforeAll(() => {
    const scriptPath = path.join(__dirname, '../../static/js/pages/problems-ui.js');
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');

    window.eval(scriptContent);
    global.ProblemsUI = window.ProblemsUI;
  });

  test('shows GTFS route ids and table-based route evidence for contradiction problems', () => {
    const html = ProblemsUI.renderSingleProblemUI({
      id: 'problem-route-1',
      stop_id: 'stop-1',
      problem: 'contradicts_route_matching',
      priority: 2,
      sloid: 'ch:1:sloid:95669:0:959883',
      osm_node_id: '123456789',
      match_type: 'route_gtfs_direction',
      routes_atlas: [
        {
          route_id: '92-55-A-j26-1',
          route_name_short: '55',
          direction_id: '0'
        }
      ],
      routes_osm: [
        {
          route_id: '92-55-j22-1',
          display_route_id: '92-55-j22-1',
          route_name: 'Bus 55: Chavannes-des-Bois → Bossy',
          direction_id: '1'
        }
      ]
    }, 0, 0, 1);

    expect(html).toContain('ATLAS Routes');
    expect(html).toContain('OSM Routes');
    expect(html).toContain('Sloid:');
    expect(html).toContain('Node ID:');
    expect(html).toContain('55 (ID: 92-55-A-j26-1) Dir: 0');
    expect(html).toContain('Bus 55: Chavannes-des-Bois → Bossy (ID: 92-55-j22-1) Dir: 1');
    expect(html).toContain('Compare route names, GTFS route IDs, and directions');
    expect((html.match(/<table class="popup-table mb-0">/g) || [])).toHaveLength(2);
    expect(html).not.toContain('<ul class="mb-0 ps-3">');
  });

  test('reloads fixed context when scrolling activates another issue in the entry', () => {
    document.body.innerHTML = `
      <div id="actionButtonsContent">
        <div class="issue-container active" data-problem-id="first"></div>
        <div class="issue-container" data-problem-id="second"></div>
      </div>
      <div id="problemPriorityDisplay"></div>
    `;

    const toNodes = target => {
      if (typeof target === 'string') return Array.from(document.querySelectorAll(target));
      return target ? [target] : [];
    };
    const toDatasetKey = key => key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const miniQuery = target => {
      const nodes = toNodes(target);
      const api = {
        data(key) {
          return nodes[0] && nodes[0].dataset[toDatasetKey(key)];
        },
        removeClass(classNames) {
          classNames.split(/\s+/).filter(Boolean).forEach(className => {
            nodes.forEach(node => node.classList.remove(className));
          });
          return api;
        },
        addClass(classNames) {
          classNames.split(/\s+/).filter(Boolean).forEach(className => {
            nodes.forEach(node => node.classList.add(className));
          });
          return api;
        },
        text(value) {
          nodes.forEach(node => { node.textContent = value; });
          return api;
        }
      };
      return api;
    };
    window.$ = global.$ = miniQuery;

    let observerCallback;
    window.IntersectionObserver = global.IntersectionObserver = jest.fn(function(callback) {
      observerCallback = callback;
      this.disconnect = jest.fn();
      this.observe = jest.fn();
    });

    const problems = [
      { id: 'first', priority: 1 },
      { id: 'second', priority: 2 }
    ];
    const state = {
      currentIndex: 0
    };
    window.ProblemsState = global.ProblemsState = {
      getCurrentEntryProblems: () => problems,
      getCurrentEntryProblemIndex: () => state.currentIndex,
      setCurrentEntryProblemIndex: jest.fn(index => { state.currentIndex = index; }),
      setCurrentProblem: jest.fn(),
      getProblemMap: () => ({ id: 'problem-map' }),
      getProblemMarkersLayer: () => ({ id: 'markers' }),
      getProblemLinesLayer: () => ({ id: 'lines' }),
      getShowContext: () => true,
      setObserver: jest.fn()
    };
    window.ProblemsRenderer = {
      drawProblemOnMap: jest.fn()
    };
    window.ProblemsMap = {
      renderProblem: jest.fn(),
      loadContextData: jest.fn()
    };

    ProblemsUI.setupIntersectionObserver();
    const secondIssue = document.querySelector('[data-problem-id="second"]');
    observerCallback([{ isIntersecting: true, target: secondIssue }]);

    expect(ProblemsState.setCurrentEntryProblemIndex).toHaveBeenCalledWith(1);
    expect(ProblemsState.setCurrentProblem).toHaveBeenCalledWith(problems[1]);
    expect(window.ProblemsMap.renderProblem).toHaveBeenCalledWith(problems[1], { fitView: true });
    expect(window.ProblemsRenderer.drawProblemOnMap).not.toHaveBeenCalled();
    expect(window.ProblemsMap.loadContextData).toHaveBeenCalledWith(problems[1]);
    expect(secondIssue.classList.contains('active')).toBe(true);
  });
});
