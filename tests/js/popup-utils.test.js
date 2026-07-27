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

  test('collapsible route controls expose and update their expanded state', () => {
    const collapsible = PopupUtils.createCollapsible('Routes', '<ul><li>14</li></ul>');
    document.body.innerHTML = collapsible.buttonHtml + collapsible.panelHtml;

    const button = document.querySelector('.popup-routes-btn');
    const panel = document.getElementById(button.getAttribute('aria-controls'));

    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(panel.getAttribute('aria-hidden')).toBe('true');

    PopupUtils.toggleCollapsible(panel.id);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(panel.getAttribute('aria-hidden')).toBe('false');
  });
});
