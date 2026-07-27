const fs = require('fs');
const path = require('path');

describe('GTFS/SLOID popup route controls', () => {
  beforeAll(() => {
    window.eval(fs.readFileSync(
      path.join(__dirname, '../../static/js/components/popup-utils.js'),
      'utf8'
    ));
    window.eval(fs.readFileSync(
      path.join(__dirname, '../../static/js/components/popup-renderer.js'),
      'utf8'
    ));
  });

  test('SLOID popups use the shared collapsible Routes list without Index-only actions', () => {
    const html = window.PopupRenderer.generateGtfsStopIdSloidPopupHtml({
      entity_type: 'atlas',
      sloid: 'ch:1:sloid:92000',
      uic_ref: '8592000',
      matched_gtfs_count: 1,
      same_uic_gtfs_count: 1,
      routes_atlas: [{
        route_id: '91-14-E-j26-1',
        route_name_short: '14',
        direction_id: '1'
      }],
      matched_gtfs: [{
        stop_id: '8507000:0:1',
        stop_name: 'Bern',
        routes_atlas: [{
          route_id: '91-14-E-j26-1',
          route_name_short: '14',
          direction_id: '1'
        }]
      }]
    }, { enableFilterLinks: false, enableRouteLinks: false });

    expect(html).toContain('popup-routes-btn');
    expect(html).toContain('Routes');
    expect(html).toContain('91-14-E-j26-1');
    expect(html).toContain('Dir: 1');
    expect(html).not.toContain('filterByRoute(');
    expect(html).not.toContain('addCustomFilter(');
  });

  test('GTFS popups use the same Routes control and ATLAS route payload contract', () => {
    const html = window.PopupRenderer.generateGtfsStopIdSloidPopupHtml({
      entity_type: 'gtfs',
      stop_id: '8507000:0:1',
      stop_name: 'Bern',
      uic_number: '8507000',
      matched_sloid_count: 0,
      candidate_atlas_count: 0,
      routes_atlas: [{
        route_id: '91-3-J-j26-1',
        route_name_short: '3',
        direction_id: '0'
      }]
    }, { enableFilterLinks: false, enableRouteLinks: false });

    expect(html).toContain('popup-routes-btn');
    expect(html).toContain('Routes');
    expect(html).toContain('91-3-J-j26-1');
    expect(html).toContain('Dir: 0');
    expect(html).not.toContain('filterByRoute(');
  });

  test('unified GTFS popup cards keep Index-only links disabled', () => {
    const html = window.PopupRenderer.generateGtfsStopIdSloidPopupHtml({
      entity_type: 'gtfs',
      stop_id: '8507000:0:1',
      stop_name: 'Bern',
      uic_number: '8507000',
      matched_sloid_count: 1,
      candidate_atlas_count: 1,
      routes_atlas: [{ route_id: '91-3-J-j26-1', route_name_short: '3', direction_id: '0' }],
      matched_sloids: [{
        sloid: 'ch:1:sloid:7000:0:1',
        atlas_designation_official: 'Bern',
        routes_atlas: [{ route_id: '91-3-J-j26-1', route_name_short: '3', direction_id: '0' }]
      }]
    }, { enableFilterLinks: false, enableRouteLinks: false });

    expect(html).toContain('popup-unified-view');
    expect(html).not.toContain('filterByRoute(');
    expect(html).not.toContain('addCustomFilter(');
  });
});
