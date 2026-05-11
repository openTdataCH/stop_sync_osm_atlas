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
});