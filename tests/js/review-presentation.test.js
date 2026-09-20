const fs = require('fs');
const path = require('path');

describe('dataset presentation across primary map surfaces', () => {
  beforeAll(() => {
    ['components/popup-utils', 'components/popup-renderer', 'pages/problems-ui', 'pages/filters'].forEach(name => {
      window.eval(fs.readFileSync(path.join(__dirname, '../../static/js/' + name + '.js'), 'utf8'));
    });
  });

  beforeEach(() => {
    window.ReviewConfig = {
      source_label: 'City & Transit', source_id_label: 'Stop ID',
      capabilities: { routes: true, gtfs_identity: false }, source_url_template: ''
    };
  });

  test('popups and problem evidence use escaped configured labels with compatibility fields', () => {
    const stop = { sloid: 'feed:123', atlas_lat: 0, atlas_lon: 0 };
    const popup = PopupRenderer.generateSingleAtlasBubbleHtml(stop, true);
    expect(popup).toContain('City &amp; Transit Stop');
    expect(popup).toContain('Stop ID:');
    expect(popup).not.toContain('ATLAS');
    expect(popup).not.toContain('atlas.app.sbb.ch');
    const problem = ProblemsUI.renderSingleProblemUI({ ...stop, id: 1, problem: 'contradicts_route_matching' }, 0, 0, 1);
    expect(problem).toContain('City &amp; Transit Routes');
    expect(problem).toContain('Stop ID:');
    expect(problem).not.toContain('ATLAS');
  });

  test('source links require available identifiers and encode IDs inside configured HTTP URLs', () => {
    window.ReviewConfig.source_url_template = 'https://transit.example/stops/{id}';
    expect(SharedUtils.sourceUrl({ sloid: 'agency:12/3' })).toBe('https://transit.example/stops/agency%3A12%2F3');
    window.ReviewConfig.source_url_template = 'https://atlas.app.sbb.ch/service-points/{uic_ref}';
    expect(SharedUtils.sourceUrl({ sloid: 'feed:123' })).toBeNull();
    expect(SharedUtils.sourceUrl({ uic_ref: '8503000' })).toContain('/8503000');
    window.ReviewConfig.source_url_template = 'javascript:alert(1)';
    expect(SharedUtils.sourceUrl({})).toBeNull();
  });

  test('disabled route capability removes route actions while retaining stop review', () => {
    window.ReviewConfig.capabilities.routes = false;
    const routes = [{ route_id: 'city:A', route_name_short: 'A' }];
    const popup = PopupRenderer.generateSingleAtlasBubbleHtml({ sloid: 'city:1', routes_atlas: routes }, true);
    expect(popup).toContain('Stop ID:');
    expect(popup).not.toContain('popup-routes-btn');
    expect(PopupUtils.formatAtlasRouteList(routes)).not.toContain('filterByRoute(');
    expect(parseSmartSearchInput('route:city:A')).toEqual({ error: 'Route review is unavailable for this dataset.' });
  });

  test('explicit source search accepts arbitrary dataset identifiers and preserves Swiss shortcuts', () => {
    expect(parseSmartSearchInput('source:agency/line:Stop 1')).toEqual({ kind: 'atlas', value: 'agency/line:Stop 1' });
    expect(parseSmartSearchInput('source:8503000')).toEqual({ kind: 'atlas', value: '8503000' });
    expect(parseSmartSearchInput('ch:1:sloid:12:0:1')).toEqual({ kind: 'atlas', value: 'ch:1:sloid:12:0:1' });
    expect(parseSmartSearchInput('node/8503000')).toEqual({ kind: 'osm', value: '8503000' });
    expect(parseSmartSearchInput('not-a-source?').error).toContain('City & Transit Stop ID');
    expect(parseSmartSearchInput('not-a-source?').error).not.toContain('SLOID');
  });
});
