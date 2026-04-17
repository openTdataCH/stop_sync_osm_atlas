const fs = require('fs');
const path = require('path');

describe('PopupUtils route formatting', () => {
  beforeAll(() => {
    const scriptPath = path.join(__dirname, '../../static/js/components/popup-utils.js');
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');

    window.eval(scriptContent);
    global.PopupUtils = window.PopupUtils;
  });

  test('does not duplicate route id when route name equals route id', () => {
    const html = PopupUtils.formatRouteList([
      {
        route_id: '91-14-E-j26-1',
        route_name: '91-14-E-j26-1',
        direction_id: '1',
      },
    ]);

    expect(html).toContain('91-14-E-j26-1');
    expect(html).not.toContain('(ID:');
    expect(html).toContain('Dir: 1');
  });

  test('shows route name with id once when name differs', () => {
    const html = PopupUtils.formatRouteList([
      {
        route_id: '91-14-E-j26-1',
        route_name: 'Route 14E',
        direction_id: '1',
      },
    ]);

    expect(html).toContain('Route 14E');
    expect(html).toContain('(ID:');
    expect(html).toContain('91-14-E-j26-1');
  });

  test('atlas route list uses clickable gtfs id and no filter icon', () => {
    const html = PopupUtils.formatAtlasRouteList([
      {
        route_id: '91-14-E-j26-1',
        route_name_short: '14',
        direction_id: '1',
      },
    ]);

    expect(html).toContain('14');
    expect(html).toContain('(ID:');
    expect(html).toContain('91-14-E-j26-1');
    expect(html).toContain('filterByRoute(');
    expect(html).not.toContain('fa-filter');
  });

  test('atlas route list does not duplicate id when name equals id', () => {
    const html = PopupUtils.formatAtlasRouteList([
      {
        route_id: '91-3-J-j26-1',
        route_name_short: '91-3-J-j26-1',
        direction_id: '0',
      },
    ]);

    expect(html).toContain('91-3-J-j26-1');
    expect(html).not.toContain('(ID:');
    expect(html).not.toContain('fa-filter');
    expect(html).toContain('Dir: 0');
  });
});
