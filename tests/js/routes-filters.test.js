const fs = require('fs');
const path = require('path');

function loadScript(relativePath) {
  window.eval(
    fs.readFileSync(path.join(__dirname, '../..', relativePath), 'utf8')
  );
}

describe('Routes operator filters', () => {
  beforeAll(() => {
    loadScript('static/js/shared/utils.js');
    loadScript('static/js/components/filter-chip-utils.js');
    loadScript('static/js/pages/routes.js');
  });

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="headerSummaryFiltersRow"></div>
      <button id="headerSummaryFiltersToggle">
        <span id="headerSummaryFiltersLabel"></span>
      </button>
      <a id="clearAllFilters" class="d-none" href="#">Clear all</a>
      <div id="headerSummaryFiltersPanel" class="d-none">
        <div id="activeFilters"></div>
      </div>
    `;
    window.routesPageConfig = {
      selectedAtlasOperators: ['AAGL', 'AAGR'],
      selectedOsmOperators: [],
      matchedFilter: 'all',
      matchFilterLabels: { all: 'All' },
      q: '',
      baseUrl: '/routes'
    };
  });

  test('renders multiple operators as an OR group with separate remove actions', () => {
    window.RoutesPageFilters.updateActiveFiltersUI();

    const activeFilters = document.getElementById('activeFilters');
    const separators = Array.from(
      activeFilters.querySelectorAll('.filter-chip-separator')
    ).map((element) => element.textContent);
    const removeButtons = Array.from(
      activeFilters.querySelectorAll('.remove-filter')
    );

    expect(separators).toEqual(['(', 'OR', ')']);
    expect(removeButtons.map((button) => button.dataset.value)).toEqual([
      'AAGL',
      'AAGR'
    ]);
    expect(document.getElementById('headerSummaryFiltersLabel').textContent)
      .toBe('Filters: 2 active');
  });

  test('removing one operator preserves the other and resets pagination', () => {
    const nextUrl = window.RoutesPageFilters.buildFilterRemovalUrl(
      'http://localhost/routes?atlas_operator=AAGL%2CAAGR&osm_operator=SBB&page=7&per_page=10',
      'operator',
      'AAGL'
    );
    const parsed = new URL(nextUrl, 'http://localhost');

    expect(parsed.searchParams.get('atlas_operator')).toBe('AAGR');
    expect(parsed.searchParams.get('osm_operator')).toBe('SBB');
    expect(parsed.searchParams.has('page')).toBe(false);
    expect(parsed.searchParams.get('per_page')).toBe('10');
  });

  test('removal also supports repeated operator parameters', () => {
    const nextUrl = window.RoutesPageFilters.buildFilterRemovalUrl(
      'http://localhost/routes?atlas_operator=AAGL&atlas_operator=AAGR',
      'operator',
      'AAGR'
    );
    const parsed = new URL(nextUrl, 'http://localhost');

    expect(parsed.searchParams.getAll('atlas_operator')).toEqual(['AAGL']);
  });
});
