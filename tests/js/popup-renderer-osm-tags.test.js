const loadBrowserScript = require('./load-browser-script');
const path = require('path');

describe('OSM popups: disused status and the full tag list', () => {
  const disused = {
    id: 7,
    stop_type: 'osm_disused',
    osm_node_id: '12089295916',
    osm_lat: 46.15397,
    osm_lon: 8.77787,
    osm_name: 'Via Pancaldi Mola',
    osm_lifecycle: 'disused',
    osm_tags: { 'disused:highway': 'bus_stop', name: 'Via <Pancaldi> Mola', public_transport: 'platform' }
  };

  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-utils.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-renderer.js'));
  });

  test('a disused element says so, never shows match metadata and lists every tag escaped', () => {
    const html = window.PopupRenderer.generatePopupHtml(disused, 'osm');

    expect(html).toContain('Disused OSM Node');
    expect(html).toContain('Out of service in OSM');
    expect(html).not.toContain('Match Type');
    expect(html).toContain('OSM tags (3)');
    expect(html).toContain('<td>disused:highway</td><td>bus_stop</td>');
    expect(html).toContain('Via &lt;Pancaldi&gt; Mola');
    expect(html.indexOf('disused:highway')).toBeLessThan(html.indexOf('public_transport'));
  });

  test('list payloads without tags render no tag section', () => {
    const html = window.PopupRenderer.generatePopupHtml({ ...disused, osm_tags: undefined }, 'osm');

    expect(html).not.toContain('OSM tags');
  });
});
