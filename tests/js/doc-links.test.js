const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const STATIC = path.join(__dirname, '../../static/js');

// tests/test_docs_rendering.py checks that every linked section exists.
describe('Links to the docs section explaining what is shown', () => {
  beforeAll(() => {
    loadBrowserScript(path.join(STATIC, 'components/popup-utils.js'));
    loadBrowserScript(path.join(STATIC, 'components/popup-renderer.js'));
    loadBrowserScript(path.join(STATIC, 'pages/problems-ui.js'));
  });

  function docLink(html) {
    const link = html.match(/<a href="([^"]+)" class="doc-link"/);
    return link && link[1];
  }

  function matchedPopup(matchType) {
    return window.PopupRenderer.generatePopupHtml(
      { id: 1, stop_type: 'matched', sloid: 'ch:1:sloid:1:1', osm_node_id: '1', match_type: matchType },
      'atlas'
    );
  }

  // One match type per rule; which section each link opens is checked by tests/test_docs_rendering.py.
  test.each([
    'sloid_identifier', 'uic_two_sided_stop', 'uic_reference_local_ref', 'name_one_osm',
    'gtfs_shared_direction', 'uic_ref_group_long_distance', 'local_ref_distance', 'distance_ratio'
  ])('a popup with match type %s names it and links to the docs', matchType => {
    const html = matchedPopup(matchType);

    expect(html).toContain(matchType);
    expect(docLink(html)).toMatch(/^\/docs\/\w+/);
  });

  test('a group distance type keyed by name links to the distance rule, not the name rule', () => {
    expect(docLink(matchedPopup('name_group_distance'))).toMatch(/^\/docs\/distance_matching#/);
  });

  test('a match type without a rule section has no doc link', () => {
    expect(docLink(matchedPopup('osm_pair_propagation'))).toBeNull();
  });

  test('the middle of a matched two-sided stop has no match type: its popup names it and links to the rule', () => {
    const html = window.PopupRenderer.generatePopupHtml(
      { id: 1, stop_type: 'effectively_matched', osm_node_id: '8', match_type: null },
      'osm'
    );

    expect(html).toContain('Middle of a matched two-sided stop');
    expect(docLink(html)).toBe('/docs/reference_matching#two-sided-stops-two_sided_stop');
  });

  test('the Problems page names the active problem type and links to its section', () => {
    document.body.innerHTML = `
      <a id="problemTypeDocLink" class="d-none"></a>
      <span id="problemPriorityDisplay"></span>`;
    const chip = document.getElementById('problemTypeDocLink');

    window.ProblemsUI.updateFloatingChips({ problem: 'duplicates', priority: 2 });
    expect(chip.classList.contains('d-none')).toBe(false);
    expect(chip.getAttribute('href')).toBe('/docs/stop_problems#duplicate-problems');
    expect(chip.textContent.trim()).toBe('Duplicates');
    expect(document.getElementById('problemPriorityDisplay').textContent).toBe('P2');

    window.ProblemsUI.updateFloatingChips({ problem: 'identifier', priority: 1 });
    expect(chip.getAttribute('href')).toBe('/docs/stop_problems#identifier-problems');
    expect(chip.textContent.trim()).toBe('OSM SLOID');

    // No problems under the filters: neither chip stays behind.
    window.ProblemsUI.updateFloatingChips(null);
    expect(chip.classList.contains('d-none')).toBe(true);
    expect(document.getElementById('problemPriorityDisplay').classList.contains('d-none')).toBe(true);
  });
});
