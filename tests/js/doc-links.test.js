const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const STATIC = path.join(__dirname, '../../static/js');

// tests/test_docs_rendering.py checks that every linked section exists.
describe('Links to the docs section explaining what is shown', () => {
  beforeAll(() => {
    loadBrowserScript(path.join(STATIC, 'shared/jquery-lite.js'));
    loadBrowserScript(path.join(STATIC, 'components/popup-utils.js'));
    loadBrowserScript(path.join(STATIC, 'components/popup-renderer.js'));
    loadBrowserScript(path.join(STATIC, 'pages/problems-ui.js'));
  });

  test.each([
    ['sloid_identifier', '/docs/reference_matching#identifier-matching-identifier'],
    ['uic_two_sided_stop', '/docs/reference_matching#two-sided-stops-two_sided_stop'],
    ['uic_reference_local_ref', '/docs/reference_matching#how-the-reference-rule-works'],
    ['name_one_osm', '/docs/name_matching'],
    ['gtfs_shared_direction', '/docs/gtfs_route_matching'],
    // A group distance type keyed by name is a distance rule, not the name rule.
    ['name_group_distance', '/docs/distance_matching#group-distance-rules-group_distance-and-group_long_distance'],
    ['uic_ref_group_long_distance', '/docs/distance_matching#group-distance-rules-group_distance-and-group_long_distance'],
    ['local_ref_distance', '/docs/distance_matching#local_ref-distance-rule-local_ref_distance'],
    ['distance_only_candidate_second_pass', '/docs/distance_matching#nearest-candidate-rules'],
    ['distance_ratio', '/docs/distance_matching#nearest-candidate-rules'],
    ['osm_pair_propagation', null]
  ])('a popup links match type %s to %s', (matchType, href) => {
    const html = window.PopupRenderer.generatePopupHtml(
      { id: 1, stop_type: 'matched', sloid: 'ch:1:sloid:1:1', osm_node_id: '1', match_type: matchType },
      'atlas'
    );
    const link = html.match(/<a href="([^"]+)" class="doc-link"/);

    expect(html).toContain(matchType);
    expect(link && link[1]).toBe(href);
  });

  test('the middle of a matched two-sided stop has no match type: its popup names it and links to the rule', () => {
    const html = window.PopupRenderer.generatePopupHtml(
      { id: 1, stop_type: 'effectively_matched', osm_node_id: '8', match_type: null },
      'osm'
    );
    const link = html.match(/<a href="([^"]+)" class="doc-link"/);

    expect(html).toContain('Middle of a matched two-sided stop');
    expect(link && link[1]).toBe('/docs/reference_matching#two-sided-stops-two_sided_stop');
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
